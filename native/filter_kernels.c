/* Independent filter kernels from recovered equations; no original code or CRT. */
typedef unsigned int u32;
typedef long long i64;
typedef union { float f; u32 u; } Bits;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused = 0;

static float fast_exp(double value) {
    if (value < -37.0) return 0;
    double encoded=value*12102203.0+1065353216.0;
    Bits a,b;
    /* Original x87 FISTP stores signed64, then consumes only its low32 bits.
       Large mode3 exponents intentionally wrap rather than becoming NaN. */
    u32 bits=encoded>=9223372036854775808.0?0:(u32)(i64)encoded;
    a.u=(bits&0x7fffffU)+0x3f800000U;b.u=bits&0xff800000U;
    float v=a.f*.32518977f;v=v+.020805772f;v=v*a.f;v=v+.65304345f;
    return v*b.f;
}

EXPORT u32 ft_filter_abi(void) {return 1;}

EXPORT int ft_filter_biquad(float *audio,u32 channels,const float *m,float *state) {
    if(!audio||!m||!state||channels<1||channels>2)return 0;
    for(u32 ch=0;ch<channels;ch++) {
        float *s=state+ch*4,x1=s[0],x2=s[1],y1=s[2],y2=s[3];
        for(u32 pos=0;pos<128;pos+=4) {
            float x[4],y[4];
            for(u32 j=0;j<4;j++)x[j]=audio[(pos+j)*channels+ch];
            for(u32 j=0;j<4;j++) {
                float a=m[28+j]*y2+m[24+j]*y1;
                a=a+m[4+j]*x[2];
                float b=m[20+j]*x2+m[16+j]*x1;
                b=m[j]*x[j]+b;a=a+b;
                b=m[12+j]*x[0]+m[8+j]*x[1];
                y[j]=a+b;
            }
            for(u32 j=0;j<4;j++)audio[(pos+j)*channels+ch]=y[j];
            x1=x[3];x2=x[2];y1=y[3];y2=y[2];
        }
        s[0]=x1;s[1]=x2;s[2]=y1;s[3]=y2;
    }
    return 1;
}

/* cfg: mode, drive start/step, attenuation start/step, mode3 factor/reference,
        rectifier mode, lower/upper starts, lower/upper steps. */
EXPORT int ft_filter_shape(float *audio,u32 channels,const float *cfg) {
    if(!audio||!cfg||channels<1||channels>2||cfg[0]<0||cfg[0]>4)return 0;
    u32 mode=(u32)cfg[0],rectifier=(u32)cfg[7];
    for(u32 ch=0;ch<channels;ch++) {
        float level=cfg[1],attenuation=cfg[3],low=cfg[8],high=cfg[9];
        for(u32 i=0;i<128;i++) {
            float sample=audio[i*channels+ch],value=sample*level,shaped=sample;
            if(mode==1) {
                float magnitude=value<0?-value:value,knee=2.0f-magnitude*3.0f;
                shaped=(3.0f-knee*knee)*.3333333f;
                if(magnitude>.6666666f)shaped=1;
                if(magnitude<=.3333333f)shaped=magnitude*2.0f;
                if(value<=0)shaped=-shaped;
            } else if(mode==2) {
                double product=(double)sample*(double)level;
                shaped=1.0f-fast_exp(product>0?-product:product);
                if(value>=0)shaped=-shaped;
            } else if(mode==3) {
                float delta=value-(-.2f);
                shaped=value==-.2f?1.0f/cfg[5]:delta/(1.0f-fast_exp(-(delta*cfg[5])));
                shaped=shaped+(-.2f)/(1.0f-cfg[6]);
                if(!(shaped<1))shaped=1;else if(!(shaped> -1))shaped=-1;
            } else if(mode==4) {
                shaped=value;if(shaped>1)shaped=1;else if(shaped< -1)shaped=-1;
            }
            if(mode)shaped=shaped*attenuation;
            if(rectifier) {
                float clipped=shaped>low?shaped:low;
                if(rectifier==2&&shaped<=0)clipped=clipped-shaped*high;
                shaped=clipped;
            }
            audio[i*channels+ch]=shaped;
            level=level+cfg[2];attenuation=attenuation+cfg[4];
            low=low+cfg[10];high=high+cfg[11];
        }
    }
    return 1;
}

/* gains: wet start/step, dry start/step, DC-block coefficient. */
EXPORT int ft_filter_mix_dc(const float *wet,const float *dry,float *output,u32 channels,
                            const float *gains,float *state) {
    if(!wet||!dry||!output||!gains||!state||channels<1||channels>2)return 0;
    float a=gains[0],b=gains[2];
    for(u32 i=0;i<128;i++) {
        for(u32 ch=0;ch<channels;ch++) {
            u32 at=i*channels+ch;
            float value=wet[at]*a+dry[at]*b;
            float result=state[ch*2+1]*gains[4]+(value-state[ch*2]);
            output[at]=result;state[ch*2]=value;state[ch*2+1]=result;
        }
        a=a+gains[1];b=b+gains[3];
    }
    return 1;
}
