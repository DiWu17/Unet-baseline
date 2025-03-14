import torch
from torch import nn
import torch.nn.functional as F
# from einops import rearrange

from timm.models.layers import trunc_normal_
import math



class HighFourierTransform(nn.Module):
    def __init__(self, mask_range=20):
        """
        Args:
            mask_range (int): 高通滤波器的中心掩码范围
        """
        super(HighFourierTransform, self).__init__()
        self.mask_range = mask_range

    def _create_high_pass_mask(self, rows, cols):
        """创建高通滤波掩码"""
        crow, ccol = rows // 2, cols // 2
        # 限制mask范围不超过图像尺寸
        mask_range = min(self.mask_range, min(crow, ccol))

        # 创建掩码
        mask = torch.ones((rows, cols), dtype=torch.float32)
        mask[crow - mask_range:crow + mask_range,
        ccol - mask_range:ccol + mask_range] = 0
        return mask

    def forward(self, x):
        """
        Args:
            x (torch.Tensor): 输入张量，形状为 [batch_size, channels, height, width]

        Returns:
            torch.Tensor: 高通滤波后的张量，保持输入形状
        """
        batch_size, channels, height, width = x.shape

        # 创建高通滤波掩码并调整形状
        mask_h = self._create_high_pass_mask(height, width)
        mask_h = mask_h.view(1, 1, height, width).to(x.device)  # [1, 1, H, W]

        # 傅里叶变换
        dft = torch.fft.fft2(x)
        dft_shift = torch.fft.fftshift(dft)

        # 应用高通滤波
        fshift_h = dft_shift * mask_h
        f_ishift_h = torch.fft.ifftshift(fshift_h)

        # 逆傅里叶变换并取实部
        img_back_h = torch.abs(torch.fft.ifft2(f_ishift_h))

        return img_back_h




class DepthWiseConv2d(nn.Module):
    def __init__(self, dim_in, dim_out, kernel_size=3, padding=1, stride=1, dilation=1):
        super().__init__()

        self.conv1 = nn.Conv2d(dim_in, dim_in, kernel_size=kernel_size, padding=padding,
                               stride=stride, dilation=dilation, groups=dim_in)
        self.norm_layer = nn.GroupNorm(4, dim_in)
        self.conv2 = nn.Conv2d(dim_in, dim_out, kernel_size=1)

    def forward(self, x):
        return self.conv2(self.norm_layer(self.conv1(x)))


class LayerNorm(nn.Module):
    r""" From ConvNeXt (https://arxiv.org/pdf/2201.03545.pdf)
    """

    def __init__(self, normalized_shape, eps=1e-6, data_format="channels_last"):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(normalized_shape))
        self.bias = nn.Parameter(torch.zeros(normalized_shape))
        self.eps = eps
        self.data_format = data_format
        if self.data_format not in ["channels_last", "channels_first"]:
            raise NotImplementedError
        self.normalized_shape = (normalized_shape,)

    def forward(self, x):
        if self.data_format == "channels_last":
            return F.layer_norm(x, self.normalized_shape, self.weight, self.bias, self.eps)
        elif self.data_format == "channels_first":
            u = x.mean(1, keepdim=True)
            s = (x - u).pow(2).mean(1, keepdim=True)
            x = (x - u) / torch.sqrt(s + self.eps)
            x = self.weight[:, None, None] * x + self.bias[:, None, None]
            return x

# 
# class group_aggregation_bridge(nn.Module):
#     def __init__(self, dim_xh, dim_xl, k_size=3, d_list=[1,2,5,7]):
#         super().__init__()
#         self.pre_project = nn.Conv2d(dim_xh, dim_xl, 1)
#         group_size = dim_xl // 2
#         self.g0 = nn.Sequential(
#             LayerNorm(normalized_shape=group_size+1, data_format='channels_first'),
#             nn.Conv2d(group_size + 1, group_size + 1, kernel_size=3, stride=1,
#                       padding=(k_size+(k_size-1)*(d_list[0]-1))//2,
#                       dilation=d_list[0], groups=group_size + 1)
#         )
#         self.g1 = nn.Sequential(
#             LayerNorm(normalized_shape=group_size+1, data_format='channels_first'),
#             nn.Conv2d(group_size + 1, group_size + 1, kernel_size=3, stride=1,
#                       padding=(k_size+(k_size-1)*(d_list[1]-1))//2,
#                       dilation=d_list[1], groups=group_size + 1)
#         )
#         self.g2 = nn.Sequential(
#             LayerNorm(normalized_shape=group_size+1, data_format='channels_first'),
#             nn.Conv2d(group_size + 1, group_size + 1, kernel_size=3, stride=1,
#                       padding=(k_size+(k_size-1)*(d_list[2]-1))//2,
#                       dilation=d_list[2], groups=group_size + 1)
#         )
#         self.g3 = nn.Sequential(
#             LayerNorm(normalized_shape=group_size+1, data_format='channels_first'),
#             nn.Conv2d(group_size + 1, group_size + 1, kernel_size=3, stride=1,
#                       padding=(k_size+(k_size-1)*(d_list[3]-1))//2,
#                       dilation=d_list[3], groups=group_size + 1)
#         )
#         self.tail_conv = nn.Sequential(
#             LayerNorm(normalized_shape=dim_xl * 2 + 4, data_format='channels_first'),
#             nn.Conv2d(dim_xl * 2 + 4, dim_xl, 1)
#         )
#     def forward(self, xh, xl, mask):
#         xh = self.pre_project(xh)
#         xh = F.interpolate(xh, size=[xl.size(2), xl.size(3)], mode ='bilinear', align_corners=True)
#         xh = torch.chunk(xh, 4, dim=1)
#         xl = torch.chunk(xl, 4, dim=1)
#         x0 = self.g0(torch.cat((xh[0], xl[0], mask), dim=1))
#         x1 = self.g1(torch.cat((xh[1], xl[1], mask), dim=1))
#         x2 = self.g2(torch.cat((xh[2], xl[2], mask), dim=1))
#         x3 = self.g3(torch.cat((xh[3], xl[3], mask), dim=1))
#         x = torch.cat((x0,x1,x2,x3), dim=1)
#         x = self.tail_conv(x)
#         return x


class Grouped_multi_axis_Hadamard_Product_Attention(nn.Module):
    def __init__(self, dim_in, dim_out, x=8, y=8):
        super().__init__()

        c_dim_in = dim_in // 4
        k_size = 3
        pad = (k_size - 1) // 2

        self.params_xy = nn.Parameter(torch.Tensor(1, c_dim_in, x, y), requires_grad=True)
        nn.init.ones_(self.params_xy)
        self.conv_xy = nn.Sequential(nn.Conv2d(c_dim_in, c_dim_in, kernel_size=k_size, padding=pad, groups=c_dim_in),
                                     nn.GELU(), nn.Conv2d(c_dim_in, c_dim_in, 1))

        self.params_zx = nn.Parameter(torch.Tensor(1, 1, c_dim_in, x), requires_grad=True)
        nn.init.ones_(self.params_zx)
        self.conv_zx = nn.Sequential(nn.Conv1d(c_dim_in, c_dim_in, kernel_size=k_size, padding=pad, groups=c_dim_in),
                                     nn.GELU(), nn.Conv1d(c_dim_in, c_dim_in, 1))

        self.params_zy = nn.Parameter(torch.Tensor(1, 1, c_dim_in, y), requires_grad=True)
        nn.init.ones_(self.params_zy)
        self.conv_zy = nn.Sequential(nn.Conv1d(c_dim_in, c_dim_in, kernel_size=k_size, padding=pad, groups=c_dim_in),
                                     nn.GELU(), nn.Conv1d(c_dim_in, c_dim_in, 1))

        self.dw = nn.Sequential(
            nn.Conv2d(c_dim_in, c_dim_in, 1),
            nn.GELU(),
            nn.Conv2d(c_dim_in, c_dim_in, kernel_size=3, padding=1, groups=c_dim_in)
        )

        self.norm1 = LayerNorm(dim_in, eps=1e-6, data_format='channels_first')
        self.norm2 = LayerNorm(dim_in, eps=1e-6, data_format='channels_first')

        self.ldw = nn.Sequential(
            nn.Conv2d(dim_in, dim_in, kernel_size=3, padding=1, groups=dim_in),
            nn.GELU(),
            nn.Conv2d(dim_in, dim_out, 1),
        )

    def forward(self, x):
        x = self.norm1(x)
        x1, x2, x3, x4 = torch.chunk(x, 4, dim=1)
        B, C, H, W = x1.size()
        # ----------xy----------#
        params_xy = self.params_xy
        x1 = x1 * self.conv_xy(F.interpolate(params_xy, size=x1.shape[2:4], mode='bilinear', align_corners=True))
        # ----------zx----------#
        x2 = x2.permute(0, 3, 1, 2)
        params_zx = self.params_zx
        x2 = x2 * self.conv_zx(
            F.interpolate(params_zx, size=x2.shape[2:4], mode='bilinear', align_corners=True).squeeze(0)).unsqueeze(0)
        x2 = x2.permute(0, 2, 3, 1)
        # ----------zy----------#
        x3 = x3.permute(0, 2, 1, 3)
        params_zy = self.params_zy
        x3 = x3 * self.conv_zy(
            F.interpolate(params_zy, size=x3.shape[2:4], mode='bilinear', align_corners=True).squeeze(0)).unsqueeze(0)
        x3 = x3.permute(0, 2, 1, 3)
        # ----------dw----------#
        x4 = self.dw(x4)
        # ----------concat----------#
        x = torch.cat([x1, x2, x3, x4], dim=1)
        # ----------ldw----------#
        x = self.norm2(x)
        x = self.ldw(x)
        return x


class ConvLayer(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.conv1 = nn.Conv2d(dim, dim, kernel_size=7, padding=3, stride=1, groups=dim,
                               padding_mode='reflect')  # depthwise conv
        self.norm1 = nn.BatchNorm2d(dim)
        self.conv2 = nn.Conv2d(dim, 4 * dim, kernel_size=1, padding=0, stride=1)
        self.act1 = nn.GELU()
        self.norm2 = nn.BatchNorm2d(dim)
        self.conv3 = nn.Conv2d(4 * dim, dim, kernel_size=1, padding=0, stride=1)
        self.act2 = nn.GELU()

    def forward(self, x):
        x = self.conv1(x)
        x = self.norm1(x)
        x = self.conv2(x)
        x = self.act1(x)
        x = self.conv3(x)
        x = self.norm2(x)
        x = self.act2(x)
        return x


class Down(nn.Sequential):
    def __init__(self, in_channels):
        super().__init__()
        self.bn = nn.BatchNorm2d(in_channels)
        self.conv = nn.Conv2d(in_channels, in_channels, kernel_size=2, stride=2)

    def forward(self, x):
        return self.conv(self.bn(x))


class Image_Prediction_Generator(nn.Module):
    def __init__(self, in_channels):
        super().__init__()
        self.in_channels = in_channels
        self.conv = nn.Conv2d(in_channels, 1, kernel_size=1, stride=1)

    def forward(self, x):
        gt_pre = self.conv(x)
        x = x + x * torch.sigmoid(gt_pre)
        return x, gt_pre


class Merge(nn.Module):
    def __init__(self, dim_in):
        super().__init__()

    def forward(self, x1, x2, gt_pre, w):
        x = x1 + x2 + torch.sigmoid(gt_pre) * x2 * w
        return x


class EGEUNet(nn.Module):

    def __init__(self, num_classes=1, input_channels=3, c_list=[8, 16, 24, 32, 48, 64], bridge=True, gt_ds=True):
        super().__init__()

        self.name = "egeunet"

        self.bridge = bridge
        self.gt_ds = gt_ds

        self.encoder1 = nn.Sequential(
            nn.Conv2d(input_channels, c_list[0], 3, stride=1, padding=1),
        )
        self.encoder2 = nn.Sequential(
            nn.Conv2d(c_list[0], c_list[1], 3, stride=1, padding=1),
        )
        self.encoder3 = nn.Sequential(
            nn.Conv2d(c_list[1], c_list[2], 3, stride=1, padding=1),
            ConvLayer(c_list[2]),
        )
        self.encoder4 = nn.Sequential(
            Grouped_multi_axis_Hadamard_Product_Attention(c_list[2], c_list[3]),
        )
        self.encoder5 = nn.Sequential(
            Grouped_multi_axis_Hadamard_Product_Attention(c_list[3], c_list[4]),
        )
        self.encoder6 = nn.Sequential(
            Grouped_multi_axis_Hadamard_Product_Attention(c_list[4], c_list[5]),
        )

        self.Down1 = Down(c_list[0])
        self.Down2 = Down(c_list[1])
        self.Down3 = Down(c_list[2])

        self.merge1 = Merge(c_list[0])
        self.merge2 = Merge(c_list[1])
        self.merge3 = Merge(c_list[2])
        self.merge4 = Merge(c_list[3])
        self.merge5 = Merge(c_list[4])

        self.pred1 = Image_Prediction_Generator(c_list[4])
        self.pred2 = Image_Prediction_Generator(c_list[3])
        self.pred3 = Image_Prediction_Generator(c_list[2])
        self.pred4 = Image_Prediction_Generator(c_list[1])
        self.pred5 = Image_Prediction_Generator(c_list[0])

        # if bridge:
        #     self.GAB1 = group_aggregation_bridge(c_list[1], c_list[0])
        #     self.GAB2 = group_aggregation_bridge(c_list[2], c_list[1])
        #     self.GAB3 = group_aggregation_bridge(c_list[3], c_list[2])
        #     self.GAB4 = group_aggregation_bridge(c_list[4], c_list[3])
        #     self.GAB5 = group_aggregation_bridge(c_list[5], c_list[4])
        #     print('group_aggregation_bridge was used')
        # if gt_ds:
        #     self.gt_conv1 = nn.Sequential(nn.Conv2d(c_list[4], 1, 1))
        #     self.gt_conv2 = nn.Sequential(nn.Conv2d(c_list[3], 1, 1))
        #     self.gt_conv3 = nn.Sequential(nn.Conv2d(c_list[2], 1, 1))
        #     self.gt_conv4 = nn.Sequential(nn.Conv2d(c_list[1], 1, 1))
        #     self.gt_conv5 = nn.Sequential(nn.Conv2d(c_list[0], 1, 1))
        #     print('gt deep supervision was used')

        self.decoder1 = nn.Sequential(
            Grouped_multi_axis_Hadamard_Product_Attention(c_list[5], c_list[4]),
        )
        self.decoder2 = nn.Sequential(
            Grouped_multi_axis_Hadamard_Product_Attention(c_list[4], c_list[3]),
        )
        self.decoder3 = nn.Sequential(
            Grouped_multi_axis_Hadamard_Product_Attention(c_list[3], c_list[2]),
        )
        self.decoder4 = nn.Sequential(
            nn.Conv2d(c_list[2], c_list[1], 3, stride=1, padding=1),
        )
        self.decoder5 = nn.Sequential(
            nn.Conv2d(c_list[1], c_list[0], 3, stride=1, padding=1),
        )
        self.ebn1 = nn.GroupNorm(4, c_list[0])
        self.ebn2 = nn.GroupNorm(4, c_list[1])
        self.ebn3 = nn.GroupNorm(4, c_list[2])
        self.ebn4 = nn.GroupNorm(4, c_list[3])
        self.ebn5 = nn.GroupNorm(4, c_list[4])
        self.dbn1 = nn.GroupNorm(4, c_list[4])
        self.dbn2 = nn.GroupNorm(4, c_list[3])
        self.dbn3 = nn.GroupNorm(4, c_list[2])
        self.dbn4 = nn.GroupNorm(4, c_list[1])
        self.dbn5 = nn.GroupNorm(4, c_list[0])

        self.highfourier = HighFourierTransform()


        self.final = nn.Conv2d(c_list[0], num_classes, kernel_size=1)

        self.apply(self._init_weights)

    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=.02)
            if isinstance(m, nn.Linear) and m.bias is not None:
                nn.init.constant_(m.bias, 0)
        elif isinstance(m, nn.Conv1d):
            n = m.kernel_size[0] * m.out_channels
            m.weight.data.normal_(0, math.sqrt(2. / n))
        elif isinstance(m, nn.Conv2d):
            fan_out = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
            fan_out //= m.groups
            m.weight.data.normal_(0, math.sqrt(2.0 / fan_out))
            if m.bias is not None:
                m.bias.data.zero_()

    def forward(self, x):

        out = self.encoder1(x)
        out = F.gelu(self.Down1(self.ebn1(out)))
        t1 = out  # b, 8, 128, 128

        out = self.encoder2(out)
        out = F.gelu(self.Down2(self.ebn2(out)))
        t2 = out  # b, 16, 64, 64

        out = self.encoder3(out)
        out = F.gelu(self.Down3(self.ebn3(out)))
        t3 = out  # b, 24, 32, 32

        out = self.encoder4(out)
        out = F.gelu(F.max_pool2d(self.ebn4(out), 2))
        t4 = out  # b, 32, 16, 16

        out = self.encoder5(out)
        out = F.gelu(F.max_pool2d(self.ebn5(out), 2))
        t5 = out  # b, 48, 8, 8

        out = self.encoder6(out)
        out = F.gelu(out)  # b, 64, 8, 8


        # decoder1


        out1 = self.decoder1(out)
        out1 = F.gelu(self.dbn1(out1))  # b, 48, 8, 8

        out1, gt_pre51 = self.pred1(out1)
        out1 = self.merge5(out1, t5, gt_pre51, 0.1)  # b, 48, 8, 8
        gt_pre51 = F.interpolate(gt_pre51, scale_factor=32, mode='bilinear', align_corners=True)

        out1 = self.decoder2(out1)
        out1 = F.gelu(
            F.interpolate(self.dbn2(out1), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 32, 16, 16
        out1, gt_pre41 = self.pred2(out1)
        out1 = self.merge4(out1, t4, gt_pre41, 0.2)  # b, 32, 16, 16
        gt_pre41 = F.interpolate(gt_pre41, scale_factor=16, mode='bilinear', align_corners=True)

        out1 = self.decoder3(out1)

        out1 = F.gelu(
            F.interpolate(self.dbn3(out1), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 24, 32, 32
        out1, gt_pre31 = self.pred3(out1)
        out1 = self.merge3(out1, t3, gt_pre31, 0.3)  # b, 24, 32, 32
        gt_pre31 = F.interpolate(gt_pre31, scale_factor=8, mode='bilinear', align_corners=True)

        out1 = self.decoder4(out1)
        out1 = F.gelu(
            F.interpolate(self.dbn4(out1), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 16, 64, 64
        out1, gt_pre21 = self.pred4(out1)
        out1 = self.merge2(out1, t2, gt_pre21, 0.4)  # b, 16, 64, 64
        gt_pre21 = F.interpolate(gt_pre21, scale_factor=4, mode='bilinear', align_corners=True)

        out1 = self.decoder5(out1)
        out1 = F.gelu(
            F.interpolate(self.dbn5(out1), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 8, 128, 128
        out1, gt_pre11 = self.pred5(out1)
        out1 = self.merge1(out1, t1, gt_pre11, 0.5)  # b, 3, 128, 128
        gt_pre11 = F.interpolate(gt_pre11, scale_factor=2, mode='bilinear', align_corners=True)

        # decoder2

        out2 = self.highfourier(out)
        out2 = self.decoder1(out2)
        out2 = F.gelu(self.dbn1(out2))  # b, 48, 8, 8

        out2, gt_pre52 = self.pred1(out2)
        out2 = self.merge5(out2, t5, gt_pre52, 0.1)  # b, 48, 8, 8
        gt_pre52 = F.interpolate(gt_pre52, scale_factor=32, mode='bilinear', align_corners=True)

        out2 = self.decoder2(out2)
        out2 = F.gelu(
            F.interpolate(self.dbn2(out2), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 32, 16, 16
        out2, gt_pre42 = self.pred2(out2)
        out2 = self.merge4(out2, t4, gt_pre42, 0.2)  # b, 32, 16, 16
        gt_pre42 = F.interpolate(gt_pre42, scale_factor=16, mode='bilinear', align_corners=True)

        out2 = self.decoder3(out2)

        out2 = F.gelu(
            F.interpolate(self.dbn3(out2), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 24, 32, 32
        out2, gt_pre32 = self.pred3(out2)
        out2 = self.merge3(out2, t3, gt_pre32, 0.3)  # b, 24, 32, 32
        gt_pre32 = F.interpolate(gt_pre32, scale_factor=8, mode='bilinear', align_corners=True)

        out2 = self.decoder4(out2)
        out2 = F.gelu(
            F.interpolate(self.dbn4(out2), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 16, 64, 64
        out2, gt_pre22 = self.pred4(out2)
        out2 = self.merge2(out2, t2, gt_pre22, 0.4)  # b, 16, 64, 64
        gt_pre22 = F.interpolate(gt_pre22, scale_factor=4, mode='bilinear', align_corners=True)

        out2 = self.decoder5(out2)
        out2 = F.gelu(
            F.interpolate(self.dbn5(out2), scale_factor=(2, 2), mode='bilinear', align_corners=True))  # b, 8, 128, 128
        out2, gt_pre12 = self.pred5(out2)
        out2 = self.merge1(out1, t1, gt_pre12, 0.5)  # b, 3, 128, 128
        gt_pre12 = F.interpolate(gt_pre12, scale_factor=2, mode='bilinear', align_corners=True)


        # max block
        gt_pre5 = torch.max(gt_pre51,gt_pre52)
        gt_pre4 = torch.max(gt_pre41, gt_pre42)
        gt_pre3 = torch.max(gt_pre31, gt_pre32)
        gt_pre2 = torch.max(gt_pre21, gt_pre22)
        gt_pre1 = torch.max(gt_pre11, gt_pre12)
        out = torch.max(out1, out2)

        out = self.final(out)
        out = F.interpolate(out, scale_factor=(2, 2), mode='bilinear', align_corners=True)  # b, num_class, H, W

        if self.gt_ds:
            #这里gt需要改成合并之后的
            return (torch.sigmoid(gt_pre5), torch.sigmoid(gt_pre4), torch.sigmoid(gt_pre3), torch.sigmoid(gt_pre2),
                    torch.sigmoid(gt_pre1)), torch.sigmoid(out)
        else:
            return torch.sigmoid(out)