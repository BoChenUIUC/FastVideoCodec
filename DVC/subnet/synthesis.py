#!/Library/Frameworks/Python.framework/Versions/3.5/bin/python3.5  
from .basics import *
import pickle
import os
import codecs
from .analysis import Analysis_net

class Synthesis_net(nn.Module):
    '''
    Decode residual
    '''
    def __init__(self, useAttn = False, channels=out_channel_N):
        super(Synthesis_net, self).__init__()
        self.deconv1 = nn.ConvTranspose2d(out_channel_M,  channels, 5, stride=2, padding=2, output_padding=1)
        torch.nn.init.xavier_normal_(self.deconv1.weight.data, (math.sqrt(2 * 1 * (out_channel_M +  channels) / (out_channel_M + out_channel_M))))
        torch.nn.init.constant_(self.deconv1.bias.data, 0.01)
        self.igdn1 = GDN( channels, inverse=True)
        self.deconv2 = nn.ConvTranspose2d( channels,  channels, 5, stride=2, padding=2, output_padding=1)
        torch.nn.init.xavier_normal_(self.deconv2.weight.data, math.sqrt(2 * 1))
        torch.nn.init.constant_(self.deconv2.bias.data, 0.01)
        self.igdn2 = GDN( channels, inverse=True)
        self.deconv3 = nn.ConvTranspose2d( channels,  channels, 5, stride=2, padding=2, output_padding=1)
        torch.nn.init.xavier_normal_(self.deconv3.weight.data, math.sqrt(2 * 1))
        torch.nn.init.constant_(self.deconv3.bias.data, 0.01)
        self.igdn3 = GDN( channels, inverse=True)
        self.deconv4 = nn.ConvTranspose2d( channels, 3, 5, stride=2, padding=2, output_padding=1)
        torch.nn.init.xavier_normal_(self.deconv4.weight.data, (math.sqrt(2 * 1 * ( channels + 3) / ( channels +  channels))))
        torch.nn.init.constant_(self.deconv4.bias.data, 0.01)
        if useAttn:
            self.layers = nn.ModuleList([])
            depth = 12
            for _ in range(depth):
                ff = FeedForward(out_channel_M)
                s_attn = Attention(out_channel_M, dim_head = 64, heads = 8)
                t_attn = Attention(out_channel_M, dim_head = 64, heads = 8)
                t_attn, s_attn, ff = map(lambda t: PreNorm(out_channel_M, t), (t_attn, s_attn, ff))
                self.layers.append(nn.ModuleList([t_attn, s_attn, ff]))
            self.frame_rot_emb = RotaryEmbedding(64)
            self.image_rot_emb = AxialRotaryEmbedding(64)
        self.useAttn = useAttn
        
    def forward(self, x):
        if self.useAttn:
            # B,C,H,W->1,BHW,C
            B,C,H,W = x.size()
            frame_pos_emb = self.frame_rot_emb(B,device=x.device)
            image_pos_emb = self.image_rot_emb(H,W,device=x.device)
            x = x.permute(0,2,3,1).reshape(1,-1,C).contiguous()
            for (t_attn, s_attn, ff) in self.layers:
                x = t_attn(x, 'b (f n) d', '(b n) f d', n = H*W, rot_emb = frame_pos_emb) + x
                x = s_attn(x, 'b (f n) d', '(b f) n d', f = B, rot_emb = image_pos_emb) + x
                x = ff(x) + x
            x = x.view(B,H,W,C).permute(0,3,1,2).contiguous()
        x = self.igdn1(self.deconv1(x))
        x = self.igdn2(self.deconv2(x))
        x = self.igdn3(self.deconv3(x))
        x = self.deconv4(x)
        return x


def build_model():
    input_image = torch.zeros([7,3,256,256])
    analysis_net = Analysis_net()
    synthesis_net = Synthesis_net()
    feature = analysis_net(input_image)
    recon_image = synthesis_net(feature)

    print("input_image : ", input_image.size())
    print("feature : ", feature.size())
    print("recon_image : ", recon_image.size())



if __name__ == '__main__':
  build_model()
