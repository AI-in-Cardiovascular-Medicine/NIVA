
# AAOCA Segmentation Tool <!-- omit in toc -->

## Table of contents <!-- omit in toc -->

- [Installation](#installation)
  - [Basic](#basic)
  - [Creating an executable file](#creating-an-executable-file)
- [Functionalities](#functionalities)
- [Configuration](#configuration)
- [Usage](#usage)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Acknowledgements](#acknowledgements)

## Installation

### Basic

```bash
    python3 -m venv env
    source env/bin/activate
    pip install poetry
    poetry install
```

If you plan on using GPU acceleration for model training and inference, make sure to install the required tools (NVIDIA toolkit, etc.) and the corresponding version of Tensorflow.

### Creating an executable file

In case you prefer a single executable file instead of running the application from the terminal or an IDE, you can follow these steps to generate an executable for **the OS you are executing the command on**, i.e. if you run this in a Linux environment, you will create an executable for Linux.\
First, you need to install the application on your system (e.g. with the commands above on Linux) and ensure it is properly set up and can be run.\
Then you can use Pyinstaller to create an executable:

```bash
pyinstaller -F --hiddenimport=pydicom.encoders.gdcm --hiddenimport=pydicom.encoders.pylibjpeg --hiddenimport=scipy.special._cdflib main.py
```

You can find the executable **main** in the **dist** folder.
If you are having trouble launching the application from the executable, try running it in a terminal to see potential errors:

```bash
./dist/main
```

## Functionalities

This application is designed for IVUS images in DICOM or NIfTi format and offers the following functionalities:

- Inspect IVUS images frame-by-frame and display DICOM metadata
- Manually **draw lumen contours** with automatic calculation of lumen area, circumference and elliptic ratio
- **Automatic segmentation** of lumen for all frames (work in progress)
- Manually tag diastolic/systolic frames
- Ability to measure up to two distances per frame which will be stored in the report
- **Auto-save** of contours and tags enabled by default with user-definable interval
- Generation of report file containing detailed metrics for each frame
- Ability to save images and segmentations as **NIfTi files**, e.g. to train a machine learning model
- Automatically extract diastolic/systolic frames (work in progress)

## Configuration

Make sure to quickly check the **config.yaml** file and configure everything to your needs.

## Usage

After the config file is set up properly, you can run the application using:

```bash
python3 main.py
```

This will open a graphical user interface (GUI) in which you have access to the above-mentioned functionalities.

## Keyboard shortcuts

For ease-of-use, this application contains several keyboard shortcuts.\
In the current state, these cannot be changed by the user (at least not without changing the source code).

- Press <kbd>Ctrl</kbd> + <kbd>O</kbd> to open a DICOM/NIfTi file
- Use the <kbd>A</kbd> and <kbd>D</kbd> keys to move through the IVUS images frame-by-frame
- If gated (diastolic/systolic) frames are available, you can move through those using <kbd>S</kbd> and <kbd>W</kbd>\
  Make sure to select which gated frames you want to traverse using the corresponding button (blue for diastolic, red for systolic)
- Press <kbd>E</kbd> to manually draw a new lumen contour\
  In case you accidentally delete a contour, you can use <kbd>Ctrl</kbd> + <kbd>Z</kbd> to undo
- Use <kbd>1</kbd>, <kbd>2</kbd> to draw measurements 1 and 2, respectively
- Use <kbd>3</kbd>, <kbd>4</kbd> or <kbd>5</kbd> to apply image filters
- Hold the right mouse button <kbd>RMB</kbd> for windowing (can be reset by pressing <kbd>R</kbd>)
- Press <kbd>C</kbd> to toggle color mode
- Press <kbd>H</kbd> to hide all contours
- Press <kbd>J</kbd> to jiggle around the current frame
- Press <kbd>Ctrl</kbd> + <kbd>S</kbd> to manually save contours (auto-save is enabled by default)
- Press <kbd>Ctrl</kbd> + <kbd>R</kbd> to generate report file
- Press <kbd>Ctrl</kbd> + <kbd>Q</kbd> to close the program
- Press <kbd>Alt</kbd> + <kbd>P</kbd> to plot the results for gated frames (difference area systole and diastole, by distance)
- Press <kbd>Alt</kbd> + <kbd>Delete</kbd> to define a range of frames to remove gating
- Press <kbd>Alt</kbd> + <kbd>S</kbd> to define a range of frames to switcht systole and diastole in gated frames

## Acknowledgements

The starting point of this project was the [DeepIVUS](https://github.com/dmolony3/DeepIVUS) public repository by [David](https://github.com/dmolony3) (cloned on May 22, 2023).
