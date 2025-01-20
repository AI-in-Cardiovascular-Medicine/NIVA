import math
import random
from glob import glob
from typing import Tuple, List, Any, Dict

import albumentations as A
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split



class DataGenerator(tf.keras.utils.Sequence):
    def __init__(self,
                 img_files: List[str],
                 mask_files: List[str],
                 batch_size: int,
                 img_size: (int, int),
                 img_channels: int = 1,
                 mask_channels: int = 1,
                 augmentation_p: float = 0.5,
                 random_rotate_p: float = 0.3,
                 vertical_flip_p: float = 0.5,
                 horizontal_flip_p: float = 0.5,
                 shuffle=True,
                 hue_p=0.5,
                 contrast_p=0.5,
                 brightness_p=0.5,
                 hue_shift_limit: int = 20,
                 sat_shift_limit: int = 30,
                 val_shift_limit: int = 20,
                 contrast_limit: float = 0.2,
                 brightness_limit: float = 0.2,
                 ):
        # nfile = glob(data_path + '/NAC/*.nii.gz')
        # train_files, val_files = train_test_split(nfile, test_size=val_size, random_state=seed)
        nac_data, mac_data = reg_data_prep(img_files, mask_files)
        self.img_paths = np.array(nac_data)
        self.mask_paths = np.array(mac_data)

        self.batch_size = batch_size
        self.shuffle = shuffle
        self.augmentation_p = augmentation_p
        self.transform = A.Compose([
            A.Rotate(limit=180, p=random_rotate_p),
            A.VerticalFlip(p=vertical_flip_p),
            A.HorizontalFlip(p=horizontal_flip_p),
            # A.CenterCrop(p=p_center_crop, height=img_size[0], width=img_size[1]),
            A.HueSaturationValue(hue_shift_limit=hue_shift_limit,
                                 sat_shift_limit=sat_shift_limit,
                                 val_shift_limit=val_shift_limit,
                                 p=hue_p),
            # A.RandomContrast(limit=contrast_limit, p=contrast_p),
            # A.RandomBrightness(limit=brightness_limit, p=brightness_p),
        ], p=self.augmentation_p)
        self.img_size = img_size
        self.img_channel = img_channels
        self.mask_channel = mask_channels
        # self.cutmix_p = cutmix_p
        # self.p_mosaic = p_mosaic
        # self.beta = beta
        self.on_epoch_end()

    def on_epoch_end(self):
        if self.shuffle:
            indices = np.random.permutation(len(self.img_paths)).astype(np.int32)
            self.img_paths, self.mask_paths = self.img_paths[indices], self.mask_paths[indices]

    def __len__(self):
        return math.ceil(len(self.img_paths) / self.batch_size)

    def __getitem__(self, idx):
        batch_img = self.img_paths[idx * self.batch_size:(idx + 1) * self.batch_size]
        batch_mask = self.mask_paths[idx * self.batch_size:(idx + 1) * self.batch_size]
        x = np.zeros((self.batch_size, *self.img_size, self.img_channel), dtype=np.float32)
        y = np.zeros((self.batch_size, *self.img_size, self.mask_channel), dtype=np.uint8)

        rnd_p = random.random()

        for i, (img, mask) in enumerate(zip(batch_img, batch_mask)):
            # img = cv2.resize(img, self.img_size)
            # mask = cv2.resize(mask, self.img_size, interpolation=cv2.INTER_NEAREST)

            augmented = self.transform(image=img.astype(np.float32), mask=mask.astype(np.uint8))
            img, mask = augmented['image'], augmented['mask']
            x[i] = img
            y[i] = mask

        # y = y.reshape((self.batch_size, *self.img_size, 1)) / 255  # normalization is done for all the samples
        y = np.concatenate([y] * self.mask_channel, axis=-1)
        x = x / 255
        return x, y


################################################################################
def load_nii_file(fpath):
    arr = nib.load(fpath)
    arr = np.asanyarray(arr.dataobj)
    if len(arr.shape) == 2:
        arr = arr[..., None]
    arr = np.swapaxes(arr, 0, 2)
    return arr


def save_float_32(fpath):
    org_arr = nib.load(fpath)
    arr = np.asanyarray(org_arr.dataobj)
    arr_changed = arr.astype(np.float32)

    img = nib.Nifti1Image(arr_changed, affine=org_arr.affine)
    name = fpath.replace("/", "_")
    nib.save(img, f"/home/aici/Desktop/{name}")


################################################################################
def show_slices(slices):
    fig, axes = plt.subplots(1, len(slices))
    for i, slice in enumerate(slices):
        axes[i].imshow(slice.T, cmap="jet", origin="lower")


def in_notebook():
    try:
        from IPython import get_ipython
        if 'IPKernelApp' not in get_ipython().config:  # pragma: no cover
            return False
    except:
        return False
    return True


def make_gen(x):
    def gen():
        i = 0
        while i < len(x):
            yield next(x)
            i += 1

    return gen


def get_datasets(data_path, val_size: float, seed=1234,
                 batch_size: int = 32, train_data_gen: Dict[str, Any] = None):
    from tensorflow.keras.preprocessing.image import ImageDataGenerator
    train_data_gen = train_data_gen or dict()
    nfile = glob(data_path + '/NAC/*.nii.gz')
    train_files, val_files = train_test_split(nfile, test_size=val_size, random_state=seed)
    nac_train_data, mac_train_data = reg_data_prep(train_files)
    nac_test_data, mac_test_data = reg_data_prep(val_files)
    n_data, nd1, nd2, nch = nac_train_data.shape
    aug1 = ImageDataGenerator(**train_data_gen)
    aug2 = ImageDataGenerator(**train_data_gen)
    nac_flow = aug1.flow(nac_train_data, batch_size=batch_size, seed=seed)
    mac_flow = aug2.flow(mac_train_data, batch_size=batch_size, seed=seed)
    gen_nac = make_gen(nac_flow)
    gen_mac = make_gen(mac_flow)
    train_dataset1 = tf.data.Dataset.from_generator(gen_nac, output_types=tf.float32,
                                                    output_shapes=(None, nd1, nd2, nch))
    train_dataset2 = tf.data.Dataset.from_generator(gen_mac, output_types=tf.uint8, output_shapes=(None, nd1, nd2, nch))
    train_dataset = tf.data.Dataset.zip((train_dataset1, train_dataset2))  # .batch(10)

    test_data_gen_args = {}
    aug1 = ImageDataGenerator(**test_data_gen_args)
    aug2 = ImageDataGenerator(**test_data_gen_args)

    nac_flow = aug1.flow(nac_test_data, batch_size=batch_size, seed=seed)
    mac_flow = aug2.flow(mac_test_data, batch_size=batch_size, seed=seed)
    gen_nac = make_gen(nac_flow)
    gen_mac = make_gen(mac_flow)
    test_dataset1 = tf.data.Dataset.from_generator(gen_nac, output_types=tf.float32,
                                                   output_shapes=(None, nd1, nd2, nch))
    test_dataset2 = tf.data.Dataset.from_generator(gen_mac, output_types=tf.uint8, output_shapes=(None, nd1, nd2, nch))
    test_dataset = tf.data.Dataset.zip((test_dataset1, test_dataset2))  # .batch(10)

    return train_dataset, test_dataset


################################################################################

################################################################################
def reg_data_prep(img_list: List[str], mask_list: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    nac_datas, mac_datas = [], []
    for img_path, mask_path in zip(img_list, mask_list):
        nac_data = load_nii_file(img_path)
        mac_data = load_nii_file(mask_path)

        mac_data = np.expand_dims(mac_data, axis=3)
        nac_data = np.expand_dims(nac_data, axis=3)
        nac_datas.append(nac_data)
        mac_datas.append(mac_data)
    nac_data_set = np.concatenate(nac_datas, axis=0)
    mac_data_set = np.concatenate(mac_datas, axis=0)
    return nac_data_set, mac_data_set

# if __name__ == '__main__':
#     flist1 = glob(DATA_PATH + '*')
#     print('Datasets:', flist1)
#     # os.chdir(CTASC_PATH)
#     DataNumbers = len(list(glob("*.nii.gz")))
#     # print('DataNumbers:', DataNumbers)
#     # flist1 = glob(DATA_PATH + '*')
#     # Path(postfix).mkdir(parents=True, exist_ok=True)
#     get_datasets(DATA_PATH, sample=DataNumbers)
