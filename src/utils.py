import torch
import torch.nn as nn
from torchmetrics import Metric
from torchmetrics.functional.segmentation import mean_iou
from torchmetrics.functional.classification import multiclass_accuracy
from torchmetrics.functional.regression import mean_absolute_error
import torch.nn.functional as F
import numpy as np
import matplotlib.pyplot as plt
import os

def init_weights(model):
    for m in model.modules():
        if isinstance(m, nn.Conv2d):
            nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
        elif isinstance(m, nn.BatchNorm2d):
            nn.init.constant_(m.weight, 1)
            nn.init.constant_(m.bias, 0)

def count_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

def mean_absolute_relative_error(preds, target):
    # mask = mask_invalid_pixels(target)
    # preds_flat = preds.masked_select(mask)
    # target_flat = target.masked_select(mask)
    #return torch.mean(torch.abs(preds_flat - target_flat)/target_flat)
    #abs_diff = torch.abs(preds - target)
    return torch.sum(torch.abs(preds - target)/target), target.shape[0]
    #return torch.sum(abs_diff), torch.sum(abs_diff/target), target.shape[0]

class MeanAbsoluteRelativeError(Metric):
    def __init__(self):
        super().__init__()
        #self.add_state("sum_abs_err", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state("sum_rel_err", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state("num_obs", default=torch.tensor(0), dist_reduce_fx="sum")

    def update(self, preds: torch.Tensor, target: torch.Tensor):
        rel, obs = mean_absolute_relative_error(preds, target)
        #self.sum_abs_err += abs
        self.sum_rel_err += rel
        self.num_obs += obs

    def compute(self):
        return self.sum_rel_err / self.num_obs
        #return self.sum_abs_err / self.num_obs
    
def angle_distance(preds, target):
    mask = mask_invalid_pixels(target)
    # preds_angle = torch.acos(preds)*180/torch.pi
    # target_angle = torch.acos(target)*180/torch.pi
    # # print(f"Preds: {preds_angle}")
    # # print(f"Targets: {target_angle}")
    # angle_diff = torch.abs(preds_angle - target_angle)
    # print(f"Angle diff: {angle_diff}")
    # print(f"Mean {torch.mean(angle_diff)}")
    # print(f"Median {torch.median(angle_diff)}")
    # print(f"Tolls {[torch.sum(angle_diff <= toll)/angle_diff.numel() for toll in [11.25, 22.5, 30]]}")
    dot_prod = torch.sum(preds*target, dim=1)
    angle_diff = torch.acos(torch.clamp(dot_prod.masked_select(mask), -1, 1)).rad2deg()
    return angle_diff, angle_diff.shape[0]

class AngleDistance(Metric):
    def __init__(self, tolls=[11.25, 22.5, 30]):
        super().__init__()
        self.tolls = tolls
        self.add_state("angle_mean", default=torch.tensor(0.0), dist_reduce_fx="sum")
        #self.add_state("angle_median", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state("angle_median", default=[], dist_reduce_fx="sum")
        self.add_state("angle_tolls", default=torch.tensor([0.0 for _ in range(len(tolls))]), dist_reduce_fx="sum")
        self.add_state("num_obs", default=torch.tensor(0), dist_reduce_fx="sum")

    def update(self, preds: torch.Tensor, target: torch.Tensor):
        angle_diff, obs = angle_distance(preds, target)
        #self.angle_mean += torch.mean(angle_diff)
        self.angle_mean += torch.sum(angle_diff)
        #self.angle_median += torch.median(angle_diff)
        self.angle_median.append(torch.median(angle_diff))
        #self.angle_tolls += torch.tensor([torch.sum(angle_diff <= toll)/angle_diff.numel() for toll in self.tolls]).to(self.angle_tolls.device)
        self.angle_tolls += torch.tensor([torch.sum(angle_diff <= toll) for toll in self.tolls]).to(self.angle_tolls.device)
        self.num_obs += obs

    def compute(self):
        #return {'mean':self.angle_mean/self.num_obs, 'median':self.angle_median/self.num_obs, 'tolls':self.angle_tolls}
        return {'mean':self.angle_mean/self.num_obs, 'median':torch.mean(torch.tensor(self.angle_median)), 'tolls':self.angle_tolls}

def add_plt(plt, data):
    for k in data.keys():
        plt[k].append(data[k].compute().cpu()) if isinstance(data[k], Metric) else plt[k].append(data[k])

def plot_dict(plt_dict, path=None):
    # nrows, ncols = len(plt_dict)//2, 2
    # _, ax = plt.subplots(nrows, ncols)
    # for i, k in enumerate(plt_dict.keys()):
    #     ax[i//ncols][i%ncols].plot(plt_dict[k])
    #     ax[i//ncols][i%ncols].set_title(k)
    # plt.savefig(path) if path else None
    for k in plt_dict.keys():
        nplots = len(plt_dict[k])
        ncols = 2
        nrows = nplots//2 if nplots %2 == 0 else nplots//2 + 1
        fig, ax = plt.subplots(nrows, ncols, figsize=(15, 15)) if nplots > 2 else plt.subplots(1, 2, figsize=(10, 10))
        fig.suptitle(k)
        for i, t in enumerate(plt_dict[k].keys()):
            if t == 'lambdas':
                for l in plt_dict[k][t].keys():
                    ax[i//ncols][i%ncols].plot(plt_dict[k][t][l], label=l)
                ax[i//ncols][i%ncols].legend(loc="upper left")
                #ax[i//ncols][i%ncols].set_title(t)
            else:
                ax[i//ncols][i%ncols].plot(plt_dict[k][t])
            ax[i//ncols][i%ncols].set_title(t)
        plt.savefig(path + k + '.png') if path else None

# def compute_lambdas(losses_seg, losses_depth, T, K):
#     w_seg = np.mean(losses_seg['new']) / np.mean(losses_seg['old'])
#     w_depth = np.mean(losses_depth['new']) / np.mean(losses_depth['old'])
#     w = F.softmax(torch.tensor([w_seg/T, w_depth/T]), dim=0)*K
#     return w

def compute_lambdas(losses_new, losses_old, K, T=2):
    w = []
    for k in losses_new.keys():
        w_tmp = losses_new[k] / losses_old[k]
        w.append(w_tmp/T)
    w = F.softmax(torch.tensor(w), dim=0)*K
    return dict(zip(losses_new.keys(), w))

# def update_losses(losses_seg, losses_depth):
#     losses_seg['old'] = losses_seg['new']
#     losses_depth['old'] = losses_depth['new']
#     losses_seg['new'] = []
#     losses_depth['new'] = []
def update_losses(losses_new, losses_old):
    for k in losses_new.keys():
        losses_old[k] = losses_new[k]
        losses_new[k] = []

def update_stats(stats, x, y):
    for t in stats.keys():
        stats[t].update(x, y)

def reset_stats(stats):
    for k in stats.keys():
        for t in stats[k].keys():
            stats[k][t].reset()

# def save_model_opt(model, opt, path):
#     torch.save(model.state_dict(), path)
#     torch.save(opt.state_dict(), path)

def ignore_index_seg(preds_seg, y_seg):
    preds_seg_flat = preds_seg.view(-1)
    y_seg_flat = y_seg.view(-1)
    pos_idx = torch.where(y_seg_flat != -1)
    preds_seg_flat = preds_seg_flat[pos_idx[0]].unsqueeze(0)
    y_seg_flat = y_seg_flat[pos_idx[0]].unsqueeze(0)
    return preds_seg_flat, y_seg_flat

def mask_invalid_pixels(y):
    mask = (y.sum(dim=1, keepdim=True) != 0).to(y.device) if len(y.shape) == 4 else (y != 0).to(y.device)
    return mask

# def save_results(model_name, dataset_name):
#     if not os.path.exists(f"../models/{dataset_name}/{model_name}"): 
#         os.makedirs(f"../models/{dataset_name}/{model_name}")
#     plt.savefig(f"../models/{model_name}/{model_name}_results.png")
    
# def visualize_results_singletask(model, img_x, img_y, device, save=False):
#     with torch.no_grad():
#         model.eval()
#         model = model.to(device)
#         img_x = img_x.to(device).to(torch.float)
#         output = model(img_x.unsqueeze(0))
        
#         plt.imshow(img_x.cpu().permute(1, 2, 0))
#         _, ax = plt.subplots(1, 2, figsize=(11, 7))
#         if model.name == 'depthnet':
#             pred = output.squeeze(0,1).cpu()
#             img_y = img_y.to(torch.float)
#             ax[0].imshow(img_y, cmap='gray')
#             ax[0].set_title('Ground Truth Depth')
#             ax[1].imshow(pred.detach().numpy(), cmap='gray')
#             ax[1].set_title('Predicted Depth')
#             plt.show()
#             print(f"Mean Absolute Error: {mean_absolute_error(pred, img_y).item()}")
#             print(f"Mean Absolute Relative Error: {mean_absolute_relative_error(pred, img_y).item()}")
#         else:
#             pred = torch.argmax(output, dim=1).squeeze(0).cpu()
#             pred_seg_flat, img_seg_flat = ignore_index_seg(pred, img_y)
#             idx = img_y==-1
#             img_y = img_y.to(torch.long)
#             img_y[idx] = 0
#             ax[0].imshow(img_y)
#             ax[0].set_title('Ground Truth Segmentation')
#             ax[1].imshow(pred.detach().numpy())
#             ax[1].set_title('Predicted Segmentation')
#             plt.show()
#             print(f"Accuracy: {multiclass_accuracy(pred, img_y, num_classes=model.classes, multidim_average='global', average='micro').item()}")
#             print(f"Mean IoU: {mean_iou(pred_seg_flat, img_seg_flat, num_classes=model.classes, per_class=False, include_background=False, input_format='index').item()}")
#         save_results(model.name) if save else None

# def visualize_results_multitask(model, img, img_seg, img_dis, device, save=False):
#     with torch.no_grad():
#         model.eval()
#         img = img.to(device).to(torch.float)
#         img_seg = img_seg.to(torch.long)
#         img_dis = img_dis.to(torch.float)
#         output_seg, output_dis = model(img.unsqueeze(0))
#         pred_seg = torch.argmax(output_seg, dim=1).squeeze(0).cpu()
#         pred_dis = output_dis.squeeze(0, 1).cpu()
#         pred_seg_flat, img_seg_flat = ignore_index_seg(pred_seg, img_seg)
#         idx = img_seg==-1
#         img_seg[idx] = 0

#         plt.imshow(img.cpu().permute(1, 2, 0))

#         _, ax = plt.subplots(2, 2, figsize=(11, 7))
#         ax[0][0].imshow(img_seg)
#         ax[0][0].set_title('Ground Truth Segmentation')
#         ax[0][1].imshow(pred_seg.detach().numpy())
#         ax[0][1].set_title('Predicted Segmentation')
#         ax[1][0].imshow(img_dis, cmap='gray')
#         ax[1][0].set_title('Ground Truth Depth')
#         ax[1][1].imshow(pred_dis.detach().numpy(), cmap='gray')
#         ax[1][1].set_title('Predicted Depth')
#         plt.show()
#         print(f"Accuracy: {multiclass_accuracy(pred_seg_flat, img_seg_flat, num_classes=model.classes, multidim_average='global', average='micro').item()}")
#         print(f"Mean IoU: {mean_iou(pred_seg_flat, img_seg_flat, num_classes=model.classes, per_class=False, include_background=False, input_format='index').item()}")
#         print(f"Mean Absolute Error: {mean_absolute_error(pred_dis, img_dis).item()}")
#         print(f"Mean Absolute Relative Error: {mean_absolute_relative_error(pred_dis, img_dis).item()}")
#         save_results(model.name) if save else None