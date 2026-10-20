/* Independent arithmetic kernels for the reconstructed dual-voice vocoder. */
typedef unsigned int u32;
typedef union { float f; u32 u; } Bits;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused;
#if defined(__x86_64__) || defined(_M_X64)
static long double sqrt80(long double x){long double result;__asm__("fsqrt":"=t"(result):"0"(x));return result;}
#else
static long double sqrt80(long double x){return sqrtl(x);}
#endif
static long double abs80(long double x){return x<0 ? -x:x;}
static float absolute(float x){Bits b;b.f=x;b.u&=0x7fffffffU;return b.f;}
EXPORT u32 ft_pitch_abi(void){return 1;}

EXPORT int ft_pitch_resample(const float *input,u32 frames,float ratio,float *output,u32 capacity,
                            float *position,float *previous,u32 *produced,u32 *consumed){
    if(!input||!output||!position||!previous||!produced||!consumed||!frames||ratio<=0)return 0;
    *produced=0;*consumed=0;
    if(!capacity)return 1;
    float pos=*position,left=0,right=0;
    u32 count=0,used=0;
    for(;;){
        if(pos>=0){
            u32 index=(u32)(int)pos&65535U;
            if(index>=frames-1){
                if(index==frames-1)*previous=input[index];
                used=frames;pos=pos-(float)frames;break;
            }
            left=input[index];right=input[index+1];
        }else{left=*previous;right=input[0];}
        if(count==capacity){
            *previous=left;
            if(pos>0){used=((u32)(int)pos&65535U)+1;pos=pos-(float)used;}
            break;
        }
        float fraction=pos<0 ? pos+1.0f : pos-(float)(u32)pos;
        float value=right-left;value=fraction*value;value=value+left;
        output[count++]=value;pos=pos+ratio;
    }
    *position=pos;*produced=count;*consumed=used;return 1;
}

static float argument(float real,float imaginary){
    if(real==0)return imaginary>0 ? 1.5707964f : (imaginary==0 ? 0.0f : -1.5707964f);
    float z=imaginary/real,phase;
    if(absolute(z)>=1.0f){
        float d=z*z;d=d+0.28f;
        phase=1.5707964f-z/d;
        if(imaginary<0)phase=phase-3.1415927f;
    }else{
        float d=z*0.28f;d=d*z;d=d+1.0f;
        phase=z/d;
        if(real<0)phase=phase+(imaginary>=0 ? 3.1415927f : -3.1415927f);
    }
    return phase;
}

EXPORT int ft_pitch_cartesian(float *spectrum,u32 bins){
    if(!spectrum||bins<2)return 0;
    for(u32 k=0;k<bins;k++){
        float real=spectrum[2*k],imaginary=spectrum[2*k+1];
        long double square=(long double)real*(long double)real;
        square=square+(long double)imaginary*(long double)imaginary;
        float magnitude=(float)sqrt80(square);
        float phase=argument(real,imaginary);
        spectrum[2*k]=magnitude;spectrum[2*k+1]=(k && k<bins-1) ? -phase : phase;
    }
    return 1;
}

EXPORT int ft_pitch_interpolate(const float *first,const float *second,float *phases,float *output,
                               u32 size,u32 hop,float fraction,u32 initialize){
    if(!first||!second||!phases||!output||!size)return 0;
    u32 bins=size/2+1;
    float first_weight=1.0f-fraction;
    float step=(float)hop*6.2831855f;step=step/(float)size;
    float expected=0.0f;
    for(u32 k=0;k<bins;k++){
        float magnitude=first[2*k]*first_weight;magnitude=magnitude+second[2*k]*fraction;
        output[2*k]=magnitude;
        if(initialize)phases[k]=first[2*k+1];
        output[2*k+1]=phases[k];
        float value=second[2*k+1]-first[2*k+1];value=value-expected;value=value+expected;value=value+phases[k];
        if(value>=3.1415927f)value=value-6.2831855f;
        if(value<-3.1415927f)value=value+6.2831855f;
        phases[k]=value;
        expected=expected+step;
        if(expected>=6.2831855f)expected=expected-6.2831855f;
    }
    return 1;
}

static float corrected_sine(float x){
    float value=absolute(x)*-0.4052847f;value=value+1.2732395f;value=value*x;
    float correction=absolute(value)*value;correction=correction-value;correction=correction*0.225f;
    return correction+value;
}
static long double endpoint_sine(long double x,u32 abs_first){
    long double second=abs_first ? abs80(x)*x : x*(long double)0.4052847f;
    second=abs_first ? second*(long double)0.4052847f : second*abs80(x);
    long double value=x*(long double)1.2732395f;value=value-second;
    long double correction=abs80(value)*value;correction=correction-value;correction=correction*(long double)0.225f;
    return correction+value;
}
EXPORT int ft_pitch_polar(float *spectrum,u32 bins){
    if(!spectrum||bins<2)return 0;
    for(u32 k=0;k<bins;k++){
        float magnitude=spectrum[2*k],phase=spectrum[2*k+1];
        float real,imaginary;
        if(k && k<bins-1){
            float angle=-phase;
            float cosine=angle+(angle>=1.5707964f ? -4.712389f : 1.5707964f);
            real=corrected_sine(cosine);imaginary=corrected_sine(angle+0.0f);
        }else{
            float cosine=phase+1.5707964f;
            if(cosine>3.1415927f)cosine=cosine-6.2831855f;
            spectrum[2*k]=(float)(endpoint_sine((long double)cosine,k==0)*(long double)magnitude);
            spectrum[2*k+1]=(float)(endpoint_sine((long double)phase,k!=0)*(long double)magnitude);
            continue;
        }
        spectrum[2*k]=real*magnitude;spectrum[2*k+1]=imaginary*magnitude;
    }
    return 1;
}

EXPORT int ft_pitch_mix(float *dry,const float *wet,u32 frames,u32 channels,
                       float old_dry,float new_dry,float old_wet,float new_wet){
    if(!dry||!wet||!frames||channels<1||channels>2)return 0;
    if(old_dry==new_dry && old_wet==new_wet){
        for(u32 i=0;i<frames*channels;i++){float value=wet[i]*new_wet;dry[i]=value+dry[i]*new_dry;}
        return 1;
    }
    float dry_step=(float)(((double)new_dry-(double)old_dry)/(double)frames);
    float wet_step=(float)(((double)new_wet-(double)old_wet)/(double)frames);
    u32 i=0;
    while(i+4<=frames){
        float dg[4],wg[4];dg[0]=old_dry;wg[0]=old_wet;
        dg[1]=dry_step+old_dry;wg[1]=wet_step+old_wet;
        dg[2]=dry_step+dg[1];
        wg[2]=wet_step+wg[1];
        dg[3]=dry_step+dg[2];wg[3]=wet_step+wg[2];
        for(u32 j=0;j<4;j++)for(u32 ch=0;ch<channels;ch++){u32 index=(i+j)*channels+ch;float value=wet[index]*wg[j];dry[index]=value+dry[index]*dg[j];}
        old_dry=dg[3]+dry_step;old_wet=wg[3]+wet_step;i+=4;
    }
    for(;i<frames;i++){for(u32 ch=0;ch<channels;ch++){u32 index=i*channels+ch;float value=wet[index]*old_wet;dry[index]=value+dry[index]*old_dry;}old_dry=old_dry+dry_step;old_wet=old_wet+wet_step;}
    return 1;
}

/* Independently reconstructed two-head triangular-crossfade delay pitch shifter. */
EXPORT int ft_multipitch(const float *input,float *output,u32 frames,u32 channels,u32 selected,
                         float *ring,u32 size,float *phase,u32 *position,float speed){
    if(!input||!output||!ring||!phase||!position||!size||size%4||channels<1||channels>2)return 0;
    float length=(float)size,half=(float)(size/2),inverse_half=1.0f/half;
    for(u32 ch=0;ch<channels;ch++){
        if(!(selected&(1U<<ch)))continue;
        float offset=phase[ch];u32 write=position[ch];float *buffer=ring+ch*size;
        for(u32 sample=0;sample<frames;sample++){
            offset=offset+speed;float other=offset+half;
            if(offset>=length)offset=offset-length;
            if(other>=length)other=other-length;
            if(offset<0)offset=offset+length;
            if(other<0)other=other+length;
            double first_extended=(double)write-(double)offset;
            double second_extended=(double)write-(double)other;
            float first_position=(float)first_extended;
            int first=(int)first_extended,second=(int)second_extended;
            if((double)first>first_extended)first--;
            if((double)second>second_extended)second--;
            float fraction=first_position-(float)first;
            if(first>=(int)size)first-=(int)size;
            if(second>=(int)size)second-=(int)size;
            if(first<0)first+=(int)size;
            if(second<0)second+=(int)size;
            u32 next_first=(u32)first+1,next_second=(u32)second+1;
            if(next_first>=size)next_first=0;
            if(next_second>=size)next_second=0;
            float first_a=buffer[first],first_b=buffer[next_first];
            float second_a=buffer[second],second_b=buffer[next_second];
            double distance=(double)offset-(double)half;
            if(distance<0)distance=-distance;
            float blend=(float)(distance*(double)inverse_half);
            buffer[write]=input[sample*channels+ch];
            float first_value=first_a*(1.0f-fraction);first_value=first_value+first_b*fraction;
            float second_value=second_a*(1.0f-fraction);second_value=second_value+second_b*fraction;
            float value=first_value*(1.0f-blend);value=value+second_value*blend;
            output[sample*channels+ch]=value;
            if(++write==size)write=0;
        }
        phase[ch]=offset;position[ch]=write;
    }
    return 1;
}
