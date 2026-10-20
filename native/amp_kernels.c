/* Independent amplifier equations, without original native code. */
typedef unsigned int U;
int _fltused;
#include "portable.h"
#define API FT_EXPORT

API int ft_amp_first(float *output,const float *audio,U frames,U channels,double *state,double b0,double b1,double a1){
    if(!output||!audio||!state||channels<1||channels>2||frames>128)return 0;
    for(U i=0;i<frames;i++)for(U c=0;c<channels;c++){
        double input=audio[i*channels+c];
        float y=(float)(state[c]+input*b0);
        double feedback=(double)y*a1;
        const double noise=(double)(float)1e-10f;
        float next=(float)(input*b1-feedback+noise);
        state[c]=(next>-noise&&next<noise)?0:(double)next;
        output[i*channels+c]=y;
    }
    return 1;
}

API int ft_amp_biquads(float *audio,U frames,U channels,const float *coefficients,float *state,U bands){
    if(!audio||!coefficients||!state||channels<1||channels>2||frames>128||bands>7)return 0;
    for(U band=0;band<bands;band++){
        const float *b=coefficients+band*5;
        float *s=state+band*4*channels;
        for(U i=0;i<frames;i++)for(U c=0;c<channels;c++){
            float x=audio[i*channels+c];
            float y=s[c]*b[1]+x*b[0];
            y=y+s[channels+c]*b[2];
            y=y-s[channels*2+c]*b[3];
            y=y-s[channels*3+c]*b[4];
            s[channels+c]=s[c];s[c]=x;
            s[channels*3+c]=s[channels*2+c];s[channels*2+c]=y;
            audio[i*channels+c]=y;
        }
    }
    return 1;
}

API int ft_amp_mix(float *wet,const float *dry,U frames,U channels,float wet_start,float wet_end,float dry_start,float dry_end){
    if(!wet||!dry||!frames||frames>128||channels<1||channels>2)return 0;
    float a=wet_start,b=dry_start;
    float step_a=(float)(((double)wet_end-(double)a)/(double)frames);
    float step_b=(float)(((double)dry_end-(double)b)/(double)frames);
    for(U i=0;i<frames;i++){
        for(U c=0;c<channels;c++){
            float w=wet[i*channels+c]*a,d=dry[i*channels+c]*b;
            wet[i*channels+c]=w+d;
        }
        a=a+step_a;b=b+step_b;
    }
    return 1;
}
