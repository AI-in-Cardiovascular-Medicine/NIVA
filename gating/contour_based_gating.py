import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseButton
from loguru import logger
from scipy.signal import find_peaks, butter, filtfilt

from gui.popup_windows.message_boxes import ErrorMessage
from gui.popup_windows.frame_range_dialog import FrameRangeDialog
from gui.right_half.right_half import toggle_diastolic_frame, toggle_systolic_frame
from report.report import report

import warnings
import time

def timing_decorator(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"{func.__name__} took {end_time - start_time:.4f} seconds")
        return result
    return wrapper

class ContourBasedGating:
    def __init__(self, main_window):
        self.main_window = main_window
        self.intramural_threshold = main_window.config.gating.intramural_threshold
        # Filter parameters
        self.lowcut = main_window.config.gating.lowcut
        self.highcut = main_window.config.gating.highcut
        self.order = main_window.config.gating.order
        # All other parameters
        self.window_size = main_window.config.gating.window_size
        self.min_height_percentile = main_window.config.gating.min_height_percentile
        self.distance = main_window.config.gating.min_distance
        self.auto_gating_threshold = main_window.config.gating.auto_gating_threshold
        self.both_extrema = main_window.config.gating.both_extrema
        # signals
        self.correlation = None
        self.blurring = None
        self.vertical_lines = []
        self.selected_line = None
        self.current_phase = None
        self.tmp_phase = None
        self.frame_marker = None
        self.phases = []
        self.systolic_indices = []
        self.diastolic_indices = []
        self.default_line_color = 'grey'
        self.default_linestyle = (0, (1, 3))

    def __call__(self):
        self.main_window.status_bar.showMessage('Contour-based gating...')
        dialog_success = self.define_intramural_part()
        if not dialog_success:
            self.main_window.status_bar.showMessage(self.main_window.waiting_status)
            return
        self.fs = self.main_window.metadata['frame_rate'] # for Butterworth filter
        self.shortest_distance = self.report_data['shortest_distance']
        self.vector_angle = self.report_data['vector_angle']
        self.vector_length = self.report_data['vector_length']
        self.crop_frames(x1=50, x2=450, y1=50, y2=450)
        self.prepare_data()
        self.plot_data()

        self.main_window.status_bar.showMessage(self.main_window.waiting_status)

    def define_intramural_part(self):
        dialog = FrameRangeDialog(self.main_window)
        if dialog.exec_():
            lower_limit, upper_limit = dialog.getInputs()
            self.report_data = report(
                self.main_window, lower_limit, upper_limit, suppress_messages=True
            )  # compute all needed data
            if self.report_data is None:
                ErrorMessage(self.main_window, 'Please ensure that an input file was read and contours were drawn')
                self.main_window.status_bar.showMessage(self.main_window.waiting_status)
                return False

            if (
                lower_limit == 0 and upper_limit == self.main_window.images.shape[0]
            ):  # automatic detection of intramural part
                mean_elliptic_ratio = self.report_data['elliptic_ratio'].rolling(window=5, closed='both').mean()

            if len(self.report_data) != upper_limit - lower_limit:
                missing_frames = [
                    frame
                    for frame in range(lower_limit + 1, upper_limit + 1)
                    if frame not in self.report_data['frame'].values
                ]
                str_missing = self.connect_consecutive_frames(missing_frames)
                ErrorMessage(self.main_window, f'Please add contours to frames {str_missing}')
                return False
            self.frames = self.main_window.images[lower_limit:upper_limit]
            self.x = self.report_data['frame'].values  # want 1-based indexing for GUI
            return True
        return False

    def connect_consecutive_frames(self, missing: list) -> str:
        nums = sorted(set(missing))
        connected = []
        i = 0
        while i < len(nums):
            j = i
            while j < len(nums) - 1 and nums[j + 1] - nums[j] == 1:
                j += 1
            if i == j:
                connected.append([nums[i]])
            else:
                connected.append(nums[i : j + 1])
            i = j + 1
        connected = [
            (f'{sublist[0]}-{sublist[-1]}' if len(sublist) > 2 else ", ".join(map(str, sublist)))
            for sublist in connected
        ]
        return ", ".join(connected)

    def crop_frames(self, x1=50, x2=450, y1=50, y2=450):
        """Crops frames to a specific region."""
        self.frames = self.frames[:, x1:x2, y1:y2]

    @timing_decorator
    def prepare_data(self):
        """Prepares data for plotting."""
        # Normalize signals
        self.correlation_nor = self.normalize_data(self.calculate_correlation())
        self.blurring_nor = self.normalize_data(self.calculate_blurring_fft())
        self.shortest_distance_nor = self.normalize_data(self.shortest_distance)
        self.vector_angle_nor = self.normalize_data(self.vector_angle)
        self.vector_length_nor = self.normalize_data(self.vector_length)

        # Apply bandpass filter to each normalized signal
        self.correlation = self.bandpass_filter(self.correlation_nor)
        self.blurring = self.bandpass_filter(self.blurring_nor)
        self.shortest_distance = self.bandpass_filter(self.shortest_distance_nor)
        self.vector_angle = self.bandpass_filter(self.vector_angle_nor)
        self.vector_length = self.bandpass_filter(self.vector_length_nor)

    def normalize_data(self, data):
        return (data - np.min(data)) / np.sum(data - np.min(data))

    @timing_decorator
    def calculate_correlation(self):
        """Calculates correlation coefficients between consecutive frames."""
        correlations = []
        for i in range(len(self.frames) - 1):
            corr = np.corrcoef(self.frames[i].ravel(), self.frames[i + 1].ravel())[0, 1]
            correlations.append(corr)
        correlations.append(0)  # to match the length of the frames
        return correlations
    
    @timing_decorator
    def calculate_blurring_fft(self):
        """Calculates blurring using Fast Fourier Transform. Takes the average of the 10% highest frequencies."""
        blurring_scores = []
        for frame in self.frames:
            fft_data = np.fft.fft2(frame)
            fft_shifted = np.fft.fftshift(fft_data)
            magnitude_spectrum = np.abs(fft_shifted)
            
            # Use np.partition to get the 10% highest frequencies
            n = len(magnitude_spectrum.ravel())
            threshold_index = int(0.9 * n)
            highest_frequencies = np.partition(magnitude_spectrum.ravel(), threshold_index)[threshold_index:]
            blurring_score = np.mean(highest_frequencies)
            blurring_scores.append(blurring_score)
        return blurring_scores

    def bandpass_filter(self, signal):
        """
        Applies a Butterworth bandpass filter to the input signal using instance parameters.

        Parameters:
        - signal (array-like): The input signal to filter.

        Returns:
        - filtered_signal (numpy.ndarray): The bandpass filtered signal.
        """
        nyquist = 0.5 * self.fs
        low = self.lowcut / nyquist
        high = self.highcut / nyquist

        # Design Butterworth bandpass filter
        b, a = butter(self.order, [low, high], btype='band')

        # Apply filter using filtfilt for zero phase distortion
        filtered_signal = filtfilt(b, a, signal)

        return filtered_signal

    def combined_signal(self, signal_list, maxima_only=False):
        """
        Combines multiple signals into one by weighting them based on the variability of their extrema.
        Assumption: The more variable the extrema, the less reliable the signal, since heart rate is regular.

        Parameters:
        - signal_list (list): A list of signals to combine.
        - maxima_only (bool): If True, only maxima are considered for variability calculation.

        Returns:
        - combined_signal (numpy.ndarray): The combined signal.
        """
        # smooth_curve for all signals
        smoothed_signals = []
        for signal in signal_list:
            smoothed_signal = self.smooth_curve(signal)
            smoothed_signals.append(smoothed_signal)

        # find extrema indices for all curves
        extrema_indices = []
        for signal in smoothed_signals:
            if maxima_only:
                extrema_indices.append(self.identify_extrema(signal)[1])
            else:
                extrema_indices.append(self.identify_extrema(signal)[0])

        # find variability in extrema indices, based on assumption that heartrate is regular
        variability = []
        for extrema in extrema_indices:
            variability.append(np.std(np.diff(extrema)))

        # calculate sum of all variabilities and then create a combined signal with weights as percent of variability
        sum_variability = np.sum(variability)
        weights = [(var / sum_variability) ** -1 for var in variability]

        combined_signal = np.zeros(len(signal_list[0]))
        for i, signal in enumerate(signal_list):
            combined_signal += weights[i] * signal

        # if name of signal list is signal_list_max then create a combined signal with the _nor otherwise signal_list_extrema
        combined_signal_nor = np.zeros(len(signal_list[0]))

        if maxima_only == True:
            signal_list_max = [
                self.correlation_nor,
                self.blurring_nor,
            ]
            for i, signal in enumerate(signal_list_max):
                combined_signal_nor += weights[i] * signal
        else:  # for extrema
            signal_list_extrema = [
                self.shortest_distance_nor,
                self.vector_angle_nor,
                self.vector_length_nor,
            ]
            for i, signal in enumerate(signal_list_extrema):
                combined_signal_nor += weights[i] * signal

        return combined_signal, combined_signal_nor

    def identify_extrema(self, signal):
        # Remove NaN and infinite values from the signal
        signal = np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0)

        # Dynamically calculate prominence based on the signal's characteristics
        min_height = np.percentile(signal, self.min_height_percentile)  # Only consider peaks above the median

        # Find maxima and minima using find_peaks with dynamic prominence
        maxima_indices, _ = find_peaks(signal, distance=self.distance, height=min_height)
        minima_indices, _ = find_peaks(-signal, distance=self.distance, height=min_height)

        # Combine maxima and minima indices into one array and sort them
        extrema_indices = np.concatenate((maxima_indices, minima_indices))
        extrema_indices = np.sort(extrema_indices)

        return extrema_indices, maxima_indices

    def smooth_curve(self, signal):
        return np.convolve(signal, np.ones(self.window_size) / self.window_size, mode='same')

    def plot_data(self):
        signal_list_max = [
            self.correlation,
            self.blurring,
        ]

        signal_list_extrema = [
            self.shortest_distance,
            self.vector_angle,
            self.vector_length,
        ]
        signal_maxima, signal_maxima_nor = self.combined_signal(signal_list_max, maxima_only=True)
        signal_extrema, signal_extrema_nor = self.combined_signal(signal_list_extrema, maxima_only=False)

        # Calculate scaling factors
        mean_max_values = np.mean(signal_maxima)
        mean_extrema_values = np.mean(signal_extrema)

        factor_diff = mean_max_values / mean_extrema_values

        # Apply scaling to ensure maxima and extrema curves are in the same range
        if factor_diff < 1:
            signal_extrema *= factor_diff
        else:
            signal_maxima *= factor_diff

        # Scale `_nor` signals to the same range
        max_signal_range = max(np.max(signal_maxima), np.max(signal_extrema))
        min_signal_range = min(np.min(signal_maxima), np.min(signal_extrema))

        max_signal_nor = max(np.max(signal_maxima_nor), np.max(signal_extrema_nor))
        min_signal_nor = min(np.min(signal_maxima_nor), np.min(signal_extrema_nor))

        scaling_factor_nor = (max_signal_range - min_signal_range) / (max_signal_nor - min_signal_nor)
        signal_maxima_nor = (signal_maxima_nor - min_signal_nor) * scaling_factor_nor
        signal_extrema_nor = (signal_extrema_nor - min_signal_nor) * scaling_factor_nor

        # Shift `_nor` signals down so their max aligns with the min of the main signals
        shift_amount = min_signal_range - np.max(signal_maxima_nor)
        signal_maxima_nor += shift_amount

        shift_amount = min_signal_range - np.max(signal_extrema_nor)
        signal_extrema_nor += shift_amount

        # Plotting
        self.fig = self.main_window.gating_display.fig
        self.fig.clear()
        self.ax = self.fig.add_subplot()

        self.ax.plot(self.x, signal_maxima, color='green', label='Image based gating')
        self.ax.plot(self.x, signal_extrema, color='yellow', label='Contour based gating')
        self.ax.plot(
            self.x, signal_maxima_nor, color='green', linestyle='dashed', label='Image based gating (unfiltered)'
        )
        self.ax.plot(
            self.x, signal_extrema_nor, color='yellow', linestyle='dashed', label='Contour based gating (unfiltered)'
        )

        self.ax.set_xlabel('Frame')
        self.ax.get_yaxis().set_visible(False)
        legend = self.ax.legend(ncol=2, loc='upper right')
        legend.set_draggable(True)

        # Interactive event connections
        plt.connect('button_press_event', self.on_click)
        plt.connect('motion_notify_event', self.on_motion)
        plt.connect('button_release_event', self.on_release)

        # Automatic gating and line drawing
        if not self.main_window.gated_frames_dia and not self.main_window.gated_frames_sys:
            self.automatic_gating(signal_maxima, signal_extrema)
        self.draw_existing_lines(self.main_window.gated_frames_dia, self.main_window.diastole_color_plt)
        self.draw_existing_lines(self.main_window.gated_frames_sys, self.main_window.systole_color_plt)

        # Layout and rendering
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            plt.tight_layout()

            if any("tight_layout" in str(w.message) for w in caught_warnings):
                plt.draw()
            else:
                plt.draw()

        return True

    def automatic_gating(self, maxima_signal, extrema_signal):
        """Automatically gates the frames based on the maxima and extrema signals. 
        The maxima signal represents the image-based gating and the extrema signal
        the contour-based gating. Usually maxima should be overlapping with extrema, but
        this is not always the case. Therefore the option to change in the config.yaml file
        The gating is based on the following assumptions:
        - Diastole frames can depict more distal parts of the coronary artery, hence sum of lumen area is higher
        
        Parameters:
        - maxima_signal (numpy.ndarray): The signal containing maxima.
        - extrema_signal (numpy.ndarray): The signal containing extrema.
        """
        # Identify local maxima and minima
        if self.both_extrema:
            logger.info('Extrema peak detection according to config.yaml')
            maxima_indices = self.identify_extrema(maxima_signal)[0]
            extrema_indices = list(self.identify_extrema(extrema_signal)[0])  # Convert to list to allow removals
        else:
            logger.info('Maxima peak detection according to config.yaml')
            maxima_indices = self.identify_extrema(maxima_signal)[1]
            extrema_indices = list(self.identify_extrema(extrema_signal)[0])

        gated_indices = []

        # Check for all indices in maxima and extrema if they are not more than 5 frames apart
        for maxima in maxima_indices:
            close_extrema = [extrema for extrema in extrema_indices if abs(maxima - extrema) <= self.auto_gating_threshold]

            if close_extrema:
                # Select the first valid extrema that is within the threshold distance
                closest_extrema = close_extrema[0]
                gated_indices.append(round((maxima + closest_extrema) / 2))
                extrema_indices.remove(closest_extrema)  # Remove to avoid duplicate gating

        # Split by every second frame, diastole frames are where lumen_area is greater in sum than the other half
        first_half = gated_indices[::2]
        second_half = gated_indices[1::2]

        sum_first_half = sum(
            [self.report_data.loc[self.report_data['frame'] == frame, 'lumen_area'].values[0] for frame in first_half]
        )
        sum_second_half = sum(
            [self.report_data.loc[self.report_data['frame'] == frame, 'lumen_area'].values[0] for frame in second_half]
        )

        if sum_first_half > sum_second_half:
            self.main_window.gated_frames_dia = first_half
            self.main_window.gated_frames_sys = second_half
        else:
            self.main_window.gated_frames_dia = second_half
            self.main_window.gated_frames_sys = first_half

        for frame in self.main_window.gated_frames_dia:
            self.main_window.data['phases'][frame] = 'D'
        for frame in self.main_window.gated_frames_sys:
            self.main_window.data['phases'][frame] = 'S'

    def on_click(self, event):
        if self.fig.canvas.cursor().shape() != 0:  # zooming or panning mode
            return
        if event.button is MouseButton.LEFT and event.inaxes:
            new_line = True
            set_dia = False
            set_sys = False
            set_slider_to = event.xdata
            if self.selected_line is not None:
                self.selected_line.set_linestyle(self.default_linestyle)
                self.selected_line = None
            if self.vertical_lines:
                # Check if click is near any existing line
                distances = [abs(line.get_xdata()[0] - event.xdata) for line in self.vertical_lines]
                if min(distances) < len(self.frames) / 100:  # sensitivity for line selection
                    self.selected_line = self.vertical_lines[np.argmin(distances)]
                    new_line = False
                    set_slider_to = self.selected_line.get_xdata()[0]
            if new_line:
                if self.current_phase == 'D':
                    color = self.main_window.diastole_color_plt
                    set_dia = True
                elif self.current_phase == 'S':
                    color = self.main_window.systole_color_plt
                    set_sys = True
                else:
                    color = self.default_line_color
                self.selected_line = plt.axvline(x=event.xdata, color=color, linestyle=self.default_linestyle)
                self.vertical_lines.append(self.selected_line)

            self.selected_line.set_linestyle('dashed')
            plt.draw()

            set_slider_to = round(set_slider_to - 1)  # slider is 0-based
            self.main_window.display_slider.set_value(set_slider_to, reset_highlights=False)

            if set_slider_to in self.main_window.gated_frames_dia or set_dia:
                self.tmp_phase = 'D'
                toggle_diastolic_frame(self.main_window, False, drag=True)
            elif set_slider_to in self.main_window.gated_frames_sys or set_sys:
                self.tmp_phase = 'S'
                toggle_systolic_frame(self.main_window, False, drag=True)

    def on_release(self, event):
        if self.fig.canvas.cursor().shape() != 0:  # zooming or panning mode
            return
        if event.button is MouseButton.LEFT and event.inaxes:
            if self.tmp_phase == 'D':
                self.main_window.diastolic_frame_box.setChecked(True)
                toggle_diastolic_frame(self.main_window, True, drag=True)
            elif self.tmp_phase == 'S':
                self.main_window.systolic_frame_box.setChecked(True)
                toggle_systolic_frame(self.main_window, True, drag=True)

        self.tmp_phase = None

    def on_motion(self, event):
        if self.fig.canvas.cursor().shape() != 0:  # zooming or panning mode
            return
        if event.button is MouseButton.LEFT and self.selected_line:
            self.selected_line.set_xdata(np.array([event.xdata]))
            if event.xdata is not None:
                self.main_window.display_slider.set_value(
                    round(event.xdata - 1), reset_highlights=False
                )  # slider is 0-based
                plt.draw()
            else:
                self.vertical_lines.remove(self.selected_line)
                self.selected_line = None
                self.tmp_phase = None
                plt.draw()

    def set_frame(self, frame):
        plt.autoscale(False)
        if self.frame_marker:
            self.frame_marker[0].remove()
        self.frame_marker = self.ax.plot(frame + 1, self.ax.get_ylim()[0], 'yo', clip_on=False)
        plt.draw()

    def draw_existing_lines(self, frames, color):
        frames = [frame for frame in frames if frame in (self.x - 1)]  # remove frames outside of user-defined range
        for frame in frames:
            self.vertical_lines.append(plt.axvline(x=frame + 1, color=color, linestyle=self.default_linestyle))

    def remove_lines(self):
        for line in self.vertical_lines:
            line.remove()
        self.vertical_lines = []
        plt.draw

    def update_color(self, color=None):
        color = color or self.default_line_color
        if self.selected_line is not None:
            self.selected_line.set_color(color)
            plt.draw()

    def reset_highlights(self):
        if self.selected_line is not None:
            self.selected_line.set_linestyle(self.default_linestyle)
            self.selected_line = None
            plt.draw()
