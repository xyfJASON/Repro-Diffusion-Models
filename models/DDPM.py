from tqdm import tqdm
from typing import Tuple

import torch
from torch import Tensor
import torch.nn as nn
import torch.nn.functional as F


def beta_schedule(total_steps: int = 1000, beta_start: float = 0.0001, beta_end: float = 0.02, mode: str = 'linear'):
    if mode == 'linear':
        return torch.linspace(beta_start, beta_end, total_steps)
    else:
        raise ValueError(f'Schedule mode {mode} is not supported.')


class DDPM:
    def __init__(self, total_steps: int = 1000, beta_schedule_mode: str = 'linear'):
        self.total_steps = total_steps
        # Define betas, alphas, and related terms
        self.betas = beta_schedule(total_steps, mode=beta_schedule_mode)
        self.alphas = 1. - self.betas
        self.alphas_cumprod = torch.cumprod(self.alphas, dim=0)
        self.alphas_cumprod_prev = torch.cat((torch.ones((1, )), self.alphas_cumprod[:-1]))
        self.sqrt_alphas_cumprod = torch.sqrt(self.alphas_cumprod)
        self.sqrt_one_minus_alphas_cumprod = torch.sqrt(1. - self.alphas_cumprod)
        self.sqrt_one_div_alphas = torch.sqrt(1.0 / self.alphas)
        self.variance = self.betas * (1. - self.alphas_cumprod_prev) / (1. - self.alphas_cumprod)

    def loss_func(self, model: nn.Module, X0: Tensor, t: Tensor, eps: Tensor = None):
        if eps is None:
            eps = torch.randn_like(X0)
        Xt = self.q_sample(X0, t, eps)
        pred_eps = model(Xt, t)
        return F.mse_loss(pred_eps, eps, reduction='sum') / X0.shape[0]

    def q_sample(self, X0: Tensor, t: Tensor, eps: Tensor = None):
        """ Sample from q(Xt | X0)
        Args:
            X0 (Tensor): [bs, C, H, W]
            t (Tensor): [bs], time step for each sample in X0, note that different sample may have different t
            eps (Tensor | None): [bs, C, H, W]
        """
        if eps is None:
            eps = torch.randn_like(X0)
        sqrt_alphas_cumprod_t = self.sqrt_alphas_cumprod[t][:, None, None, None].to(device=X0.device)
        sqrt_one_minus_alphas_cumprod_t = self.sqrt_one_minus_alphas_cumprod[t][:, None, None, None].to(device=X0.device)
        return sqrt_alphas_cumprod_t * X0 + sqrt_one_minus_alphas_cumprod_t * eps

    @torch.no_grad()
    def p_sample(self, model: nn.Module, Xt: Tensor, t: int):
        """ Sample from p_theta(X{t-1} | Xt)
        Args:
            model (nn.Module): UNet model
            Xt (Tensor): [bs, C, H, W]
            t (int): time step for all samples in Xt, note that all samples have the same t
        """
        sqrt_one_minus_alphas_cumprod_t = self.sqrt_one_minus_alphas_cumprod[t].to(device=Xt.device)
        sqrt_one_div_alphas_t = self.sqrt_one_div_alphas[t].to(device=Xt.device)
        betas_t = self.betas[t].to(device=Xt.device)

        # Calculate mu_t
        eps_pred = model(Xt, torch.full((Xt.shape[0], ), t, device=Xt.device, dtype=torch.long))
        mu_t = sqrt_one_div_alphas_t * (Xt - betas_t / sqrt_one_minus_alphas_cumprod_t * eps_pred)
        if t == 0:
            return mu_t

        # Calculate sigma_t
        sigma_t = torch.sqrt(self.variance[t]).to(device=Xt.device)
        return mu_t + sigma_t * torch.randn_like(Xt)

    @torch.no_grad()
    def sample(self, model: nn.Module, shape: Tuple[int, int, int, int]):
        device = next(model.parameters()).device
        img = torch.randn(shape, device=device)
        imgs = [img]
        for t in tqdm(range(self.total_steps-1, -1, -1), leave=False, desc='Sampling'):
            img = self.p_sample(model, img, t)
            imgs.append(img)
        return imgs