import torch
from torch.utils.data.dataset import Dataset
import numpy as np

import os
import glob

class NYUv2Dataset(Dataset):
    def __init__(self, root="./nyuv2_preprocessed", split="train"):
        self.root = root
        self.split = split
        self.images = glob.glob(os.path.join(root, split, "image", "*.npy"))
        self.labels = glob.glob(os.path.join(root, split, "label", "*.npy"))
        self.depth = glob.glob(os.path.join(root, split, "depth", "*.npy"))
        self.normals = glob.glob(os.path.join(root, split, "normal", "*.npy"))
        self.images.sort()
        self.labels.sort()
        self.depth.sort()
        self.normals.sort()

    def __len__(self):
        return len(self.images)
    
    def __getitem__(self, idx):
        image = torch.from_numpy(np.load(self.images[idx])).permute(2, 0, 1)
        label = torch.from_numpy(np.load(self.labels[idx]))
        depth = torch.from_numpy(np.load(self.depth[idx])).squeeze(2)
        normal = torch.from_numpy(np.load(self.normals[idx])).permute(2, 0, 1)
        return image, label, depth, normal