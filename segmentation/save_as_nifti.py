import os

from monailabel.transform.writer import write_nifti
from PyQt5.QtWidgets import QErrorMessage
from PyQt5.QtCore import Qt

from input_output.contours import contoursToMask


def save_as_nifti(window):
    if not window.image:
        warning = QErrorMessage(window)
        warning.setWindowModality(Qt.WindowModal)
        warning.showMessage('Cannot save as NIfTI before reading DICOM file')
        warning.exec_()
        return

    contoured_frames = [
        frame for frame in range(window.numberOfFrames) if window.lumen[0][frame] or window.plaque[0][frame]
    ]  # find frames with contours (no need to save the others)

    out_path = os.path.splitext(window.file_name)[0]  # remove file extension
    mask = contoursToMask(window.images[contoured_frames], window.lumen, window.plaque)
    write_nifti(mask, filename=f'{out_path}_mask.nii.gz')
    write_nifti(window.images[contoured_frames, :, :], filename=f'{out_path}.nii.gz')
 