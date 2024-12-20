from __future__ import division, absolute_import
import torch
from torch import nn
from torch.nn import functional as F

class ConvLayer(nn.Module):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        padding=0,
        groups=1
    ):
        super(ConvLayer, self).__init__()
        self.conv = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size,
            stride=stride,
            padding=padding,
            bias=False,
            groups=groups
        )
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        return x


class Conv1x1(nn.Module):
    def __init__(self, in_channels, out_channels, stride=1, groups=1):
        super(Conv1x1, self).__init__()
        self.conv = nn.Conv2d(
            in_channels,
            out_channels,
            1,
            stride=stride,
            padding=0,
            bias=False,
            groups=groups
        )
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        return x


class Conv1x1Linear(nn.Module):
    def __init__(self, in_channels, out_channels, stride=1):
        super(Conv1x1Linear, self).__init__()
        self.conv = nn.Conv2d(
            in_channels, out_channels, 1, stride=stride, padding=0, bias=False
        )
        self.bn = nn.BatchNorm2d(out_channels)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        return x


class Conv3x3(nn.Module):
    def __init__(self, in_channels, out_channels, stride=1, groups=1):
        super(Conv3x3, self).__init__()
        self.conv = nn.Conv2d(
            in_channels,
            out_channels,
            3,
            stride=stride,
            padding=1,
            bias=False,
            groups=groups
        )
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        return x


class LightConv3x3(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(LightConv3x3, self).__init__()
        self.conv1 = nn.Conv2d(
            in_channels, out_channels, 1, stride=1, padding=0, bias=False
        )
        self.conv2 = nn.Conv2d(
            out_channels,
            out_channels,
            3,
            stride=1,
            padding=1,
            bias=False,
            groups=out_channels
        )
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.bn(x)
        x = self.relu(x)
        return x

class ChannelGate(nn.Module):
    def __init__(
        self,
        in_channels,
        num_gates=None,
        return_gates=False,
        gate_activation='sigmoid',
        reduction=16,
        layer_norm=False
    ):
        super(ChannelGate, self).__init__()
        if num_gates is None:
            num_gates = in_channels
        self.return_gates = return_gates
        self.global_avgpool = nn.AdaptiveAvgPool2d(1)
        self.fc1 = nn.Conv2d(
            in_channels,
            in_channels // reduction,
            kernel_size=1,
            bias=True,
            padding=0
        )
        self.norm1 = None
        if layer_norm:
            self.norm1 = nn.LayerNorm((in_channels // reduction, 1, 1))
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Conv2d(
            in_channels // reduction,
            num_gates,
            kernel_size=1,
            bias=True,
            padding=0
        )
        if gate_activation == 'sigmoid':
            self.gate_activation = nn.Sigmoid()
        elif gate_activation == 'relu':
            self.gate_activation = nn.ReLU(inplace=True)
        elif gate_activation == 'linear':
            self.gate_activation = None
        else:
            raise RuntimeError(
                "Unknown gate activation: {}".format(gate_activation)
            )

    def forward(self, x):
        input = x
        x = self.global_avgpool(x)
        x = self.fc1(x)
        if self.norm1 is not None:
            x = self.norm1(x)
        x = self.relu(x)
        x = self.fc2(x)
        if self.gate_activation is not None:
            x = self.gate_activation(x)
        if self.return_gates:
            return x
        return input * x


class OSBlock(nn.Module):
    def __init__(self, in_channels, out_channels, **kwargs):
        super(OSBlock, self).__init__()
        mid_channels = out_channels // 4
        self.conv1 = Conv1x1(in_channels, mid_channels)
        self.conv2a = LightConv3x3(mid_channels, mid_channels)
        self.conv2b = nn.Sequential(
            LightConv3x3(mid_channels, mid_channels),
            LightConv3x3(mid_channels, mid_channels),
        )
        self.conv2c = nn.Sequential(
            LightConv3x3(mid_channels, mid_channels),
            LightConv3x3(mid_channels, mid_channels),
            LightConv3x3(mid_channels, mid_channels),
        )
        self.conv2d = nn.Sequential(
            LightConv3x3(mid_channels, mid_channels),
            LightConv3x3(mid_channels, mid_channels),
            LightConv3x3(mid_channels, mid_channels),
            LightConv3x3(mid_channels, mid_channels),
        )
        self.gate = ChannelGate(mid_channels)
        self.conv3 = Conv1x1Linear(mid_channels, out_channels)
        self.downsample = None
        if in_channels != out_channels:
            self.downsample = Conv1x1Linear(in_channels, out_channels)

    def forward(self, x):
        residual = x
        x1 = self.conv1(x)
        x2a = self.conv2a(x1)
        x2b = self.conv2b(x1)
        x2c = self.conv2c(x1)
        x2d = self.conv2d(x1)
        x2 = self.gate(x2a) + self.gate(x2b) + self.gate(x2c) + self.gate(x2d)
        x3 = self.conv3(x2)
        if self.downsample is not None:
            residual = self.downsample(residual)
        out = x3 + residual
        return F.relu(out)


##########
# Network architecture
##########
class BaseNet(nn.Module):

    def _make_layer(
        self, block, layer, in_channels, out_channels, reduce_spatial_size
    ):
        layers = []

        layers.append(block(in_channels, out_channels))
        for i in range(1, layer):
            layers.append(block(out_channels, out_channels))

        if reduce_spatial_size:
            layers.append(
                nn.Sequential(
                    Conv1x1(out_channels, out_channels),
                    nn.AvgPool2d(2, stride=2)
                )
            )

        return nn.Sequential(*layers)

    def _construct_fc_layer(self, fc_dims, input_dim, dropout_p=None):
        if fc_dims is None or fc_dims < 0:
            self.feature_dim = input_dim
            return None

        if isinstance(fc_dims, int):
            fc_dims = [fc_dims]

        layers = []
        for dim in fc_dims:
            layers.append(nn.Linear(input_dim, dim))
            layers.append(nn.BatchNorm1d(dim))
            layers.append(nn.ReLU(inplace=True))
            if dropout_p is not None:
                layers.append(nn.Dropout(p=dropout_p))
            input_dim = dim

        self.feature_dim = fc_dims[-1]

        return nn.Sequential(*layers)

    def init_params(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(
                    m.weight, mode='fan_out', nonlinearity='relu'
                )
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)

            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

            elif isinstance(m, nn.BatchNorm1d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0, 0.01)
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
class OSNet(BaseNet):

    def __init__(
        self,
        num_classes,
        blocks,
        layers,
        channels,
        feature_dim=512,
        loss='softmax',
        pool='avg',
        **kwargs
    ):
        super(OSNet, self).__init__()
        num_blocks = len(blocks)
        assert num_blocks == len(layers)
        assert num_blocks == len(channels) - 1
        self.loss = loss
        self.num_experts = 5
        self.channel_sizes = channels[0:]  # Assume channels list matches the outputs from each expert

        # convolutional backbone
        self.conv1 = ConvLayer(3, channels[0], 7, stride=2, padding=3)
        
        self.maxpool = nn.MaxPool2d(3, stride=2, padding=1)
        
        self.conv2 = self._make_layer(
            blocks[0],
            layers[0],
            channels[0],
            channels[1],
            reduce_spatial_size=True
        )
        
        self.conv3 = self._make_layer(
            blocks[1],
            layers[1],
            channels[1],
            channels[2],
            reduce_spatial_size=True
        )
        
        self.conv4 = self._make_layer(
            blocks[2],
            layers[2],
            channels[2],
            channels[3],
            reduce_spatial_size=False
        )
        
        self.conv5 = Conv1x1(channels[3], channels[3])

        expert_channels = [32,128,192,256,256]
        self.experts = nn.ModuleList([
            nn.Sequential(
                nn.Conv2d(channels, channels*2, kernel_size=1, padding=0),
                nn.ReLU()
            ) for channels in expert_channels
        ])
        self.experts1 = nn.Sequential(
                nn.Conv2d(256, 512, kernel_size=1, padding=0),
                nn.ReLU(),
            ) 
        self.experts2 = nn.Sequential(
                nn.Conv2d(384, 512, kernel_size=1, padding=0),
                nn.ReLU(),
            )

        self.gate = nn.Sequential(
            nn.Linear(512, 5),
            nn.Softmax(dim=1)
        )

    def forward(self, x):
        experts = []
        experts1 = []
        x = self.conv1(x)
        experts.append(x)
        x = self.maxpool(x)
        x2 = self.conv2(x)     
        experts.append(x2)
        x3 = self.conv3(x2) 
        experts.append(x3)
        x4 = self.conv4(x3)  
        experts.append(x4)
        x5 = self.conv5(x4)  
        experts.append(x5)
        
        for i in range(len(experts)):
            output = self.experts[i](experts[i])
            experts[i] = output
            if i >0:
                experts1.append(output)    
          
        for i in range(len(experts1)):
            if i==0:
                output = self.experts1(experts1[i])
                output = F.interpolate(output, scale_factor=0.5, mode='bilinear', align_corners=False)
                experts1[i] = output
            if i==1:
                output = self.experts2(experts1[i])
                experts1[i] = output
            
        gate_input = torch.mean(experts1[-1], dim=[2, 3])  
        gate_output = self.gate(gate_input)
        combined_output = sum(gate_output[:, i].unsqueeze(1).unsqueeze(2).unsqueeze(3) * experts1[i] for i in range(4))

        return combined_output, experts

def load_osnet_weights():
  net = OSNet(
        num_classes=1000,
        blocks=[OSBlock, OSBlock, OSBlock],
        layers=[2, 2, 2],
        channels=[32, 128, 192, 256],
        loss='softmax',
    )  
  return net

class student_net(nn.Module):
    def __init__(self):
        super(student_net, self).__init__()
        self.vgg = load_osnet_weights()  
        self.de_pred = nn.Sequential(
                                    nn.ConvTranspose2d(512,256,4,stride=2,padding=1,output_padding=0,bias=True),
                                    nn.ReLU(),
                                    nn.ConvTranspose2d(256,128,4,stride=2,padding=1,output_padding=0,bias=True),
                                    nn.ReLU(),
                                    nn.ConvTranspose2d(128,64,4,stride=2,padding=1,output_padding=0,bias=True),
                                    nn.ReLU(),
                                    nn.ConvTranspose2d(64,1,4,stride=2,padding=1,output_padding=0,bias=True),
                                    nn.ReLU(),
                                    )
    def forward(self, x):  
        combined_output, experts = self.vgg(x)
        x = self.de_pred(combined_output)
        return x, experts
