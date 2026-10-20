/* Independent scalar DSP kernels. No original executable code or CRT imports. */
typedef unsigned int u32;
typedef unsigned long long u64;
typedef long long i64;
typedef union { float f; u32 u; } FloatBits;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused = 0;

static float absolute(float v) { FloatBits b; b.f=v; b.u &= 0x7fffffffU; return b.f; }

static double fast_db(float amplitude) {
    FloatBits bits, mantissa;
    bits.f=amplitude;
    mantissa.u=(bits.u & 0x7fffffU)+0x3f800000U;
    double t=((double)mantissa.f-1.0)/((double)mantissa.f+1.0);
    double polynomial=t*t*(double)0.33333334f+1.0;
    double logarithm=((int)((bits.u>>23)&255)-127)*(double)0.6931472f+(t+t)*polynomial;
    return logarithm*(double)0.4342945f*20.0;
}

static float fast_pow10(float exponent) {
    if (exponent < -37.0f) return 0.0f;
    u32 bits=(u32)(i64)((double)exponent*27866352.0+1065353216.0);
    FloatBits mantissa, scale;
    mantissa.u=(bits&0x7fffffU)+0x3f800000U;
    scale.u=bits&0xff800000U;
    float a=mantissa.f*0.32518977f;
    a=a+0.020805772f;
    a=a*mantissa.f;
    a=a+0.65304345f;
    return a*scale.f;
}

EXPORT u32 ft_dsp_abi(void) { return 1; }

EXPORT int ft_limiter(float *audio, u32 frames, u32 channels, u32 linked,
                     u32 delay_frames, float *delay, u32 *position,
                     float *reduction, float *peak, i64 *countdown, u32 first,
                     float threshold, float ratio_factor, float attack, float release) {
    if (!audio || !delay || !position || !reduction || !peak || !countdown ||
        channels<1 || channels>2 || !delay_frames || *position>=delay_frames) return 0;
    u32 groups=linked ? 1 : channels;
    if (first) {
        u32 scan=frames<delay_frames ? frames : delay_frames;
        for (u32 ch=0;ch<channels;ch++) {
            u32 group=linked ? 0 : ch;
            for (u32 i=0;i<scan;i++) {
                float value=absolute(audio[i*channels+ch]);
                int replace=(linked && channels>1) ? peak[group]<value : peak[group]<=value;
                if (replace) { peak[group]=value; countdown[group]=scan-i; }
            }
        }
    }
    float over[2];
    for (u32 group=0;group<groups;group++) {
        double value=fast_db(peak[group])-(double)threshold;
        over[group]=(float)(value>0.0 ? value : 0.0);
    }
    u32 pos=*position;
    for (u32 i=0;i<frames;i++) {
        float amplitudes[2], delayed[2], levels[2];
        amplitudes[0]=absolute(audio[i*channels]);
        if (channels==2) {
            amplitudes[1]=absolute(audio[i*channels+1]);
            if (linked && amplitudes[0]<amplitudes[1]) amplitudes[0]=amplitudes[1];
        }
        for (u32 ch=0;ch<channels;ch++) {
            delayed[ch]=delay[pos*channels+ch];
            delay[pos*channels+ch]=audio[i*channels+ch];
        }
        pos++;
        if (pos==delay_frames) pos=0;
        for (u32 group=0;group<groups;group++) {
            if (countdown[group]==0 || peak[group]<amplitudes[group]) {
                peak[group]=amplitudes[group]; countdown[group]=delay_frames;
                double value=fast_db(amplitudes[group])-(double)threshold;
                over[group]=(float)(value>0.0 ? value : 0.0);
            } else countdown[group]--;
            float coefficient=over[group]>=reduction[group] ? attack : release;
            float value=reduction[group]-over[group];
            value=value*coefficient;
            value=value+over[group];
            reduction[group]=value;
            levels[group]=fast_pow10(value*ratio_factor);
        }
        for (u32 ch=0;ch<channels;ch++) audio[i*channels+ch]=delayed[ch]*levels[linked ? 0 : ch];
    }
    *position=pos;
    return 1;
}

EXPORT int ft_equalizer(float *audio, u32 frames, u32 channels, const float *coefficients, float *history) {
    if (!audio || !coefficients || !history || channels<1 || channels>2) return 0;
    float b0=coefficients[0], b1=coefficients[1], b2=coefficients[2], a1=coefficients[3], a2=coefficients[4];
    for (u32 ch=0;ch<channels;ch++) {
        float x1=history[ch*4], x2=history[ch*4+1], y1=history[ch*4+2], y2=history[ch*4+3];
        for (u32 i=0;i<frames;i++) {
            float input=audio[i*channels+ch];
            float value=x2*b2;
            value=value+input*b0;
            value=x1*b1+value;
            value=y2*a2+value;
            value=y1*a1+value;
            x2=x1; x1=input; y2=y1; y1=value;
            audio[i*channels+ch]=value;
        }
        history[ch*4]=x1; history[ch*4+1]=x2; history[ch*4+2]=y1; history[ch*4+3]=y2;
    }
    return 1;
}

static int dynamics(float *audio, u32 frames, u32 channels, u32 linked,
                  float *powers, float *reduction, float threshold, float ratio_minus_one,
                  float power_coefficient, float attack, float release, u32 compressor) {
    if (!audio || !powers || !reduction || channels<1 || channels>2) return 0;
    u32 groups=linked ? 1 : channels;
    float inverse_channels=1.0f/(float)channels;
    for (u32 i=0;i<frames;i++) {
        float squared[2], levels[2];
        for (u32 ch=0;ch<channels;ch++) squared[ch]=audio[i*channels+ch]*audio[i*channels+ch];
        if (linked) {
            float sum=0.0f;
            for (u32 ch=0;ch<channels;ch++) sum=sum+squared[ch];
            squared[0]=sum*inverse_channels;
        }
        for (u32 group=0;group<groups;group++) {
            float power=squared[group]+1e-25f;
            float value=powers[group]-power;
            value=value*power_coefficient;
            value=value+power;
            powers[group]=value;
            double under=compressor ? fast_db(value)*0.5-(double)threshold : (double)threshold-fast_db(value)*0.5;
            float target=(float)(under>0.0 ? under : 0.0);
            float coefficient=target>=reduction[group] ? (compressor ? attack : release) : (compressor ? release : attack);
            value=reduction[group]-target;
            value=value*coefficient;
            value=value+target;
            reduction[group]=value;
            float exponent=compressor ? value*ratio_minus_one : -(value*ratio_minus_one);
            exponent=exponent*0.05f;
            levels[group]=fast_pow10(exponent);
        }
        for (u32 ch=0;ch<channels;ch++) audio[i*channels+ch]=audio[i*channels+ch]*levels[linked ? 0 : ch];
    }
    return 1;
}

EXPORT int ft_gate(float *audio, u32 frames, u32 channels, u32 linked,
                  float *powers, float *reduction, float threshold, float ratio_minus_one,
                  float power_coefficient, float attack, float release) {
    return dynamics(audio,frames,channels,linked,powers,reduction,threshold,ratio_minus_one,power_coefficient,attack,release,0);
}

EXPORT int ft_compressor(float *audio, u32 frames, u32 channels, u32 linked,
                  float *powers, float *reduction, float threshold, float ratio_factor,
                  float power_coefficient, float attack, float release) {
    return dynamics(audio,frames,channels,linked,powers,reduction,threshold,ratio_factor,power_coefficient,attack,release,1);
}

EXPORT int ft_rms_power(const float *audio, u32 frames, u32 channels, float *powers) {
    if (!audio || !powers || !frames || channels<1 || channels>2) return 0;
    for (u32 ch=0;ch<channels;ch++) {
        float sum=0.0f;
        for (u32 i=0;i<frames;i++) {
            float sample=audio[i*channels+ch];
            float square=sample*sample;
            sum=sum+square;
        }
        powers[ch]=sum/(float)frames;
    }
    return 1;
}

EXPORT int ft_amp_compression(float *audio, u32 frames, u32 channels, float *states) {
    if (!audio || !states || channels<1 || channels>2) return 0;
    for (u32 ch=0;ch<channels;ch++) {
        float *state=states+ch*(0x498/4);
        for (u32 i=0;i<frames;i++) {
            float source=audio[i*channels+ch]*state[20];
            float envelope=absolute(source);
            if (envelope>=1.0f) envelope=1.0f;
            envelope=envelope-state[2];
            if (envelope<=0.0f) envelope=0.0f;
            float filtered=state[22]*state[5];
            filtered=filtered+envelope*state[4];
            filtered=filtered*0.5f;
            filtered=filtered-state[23]*state[6];
            state[21]=source; state[22]=envelope; state[23]=filtered;
            float location=filtered*255.0f;
            int index=(int)location;
            if (index < -38 || index >= 255) return 0;
            int floor_index=index;
            if (location<(float)index) floor_index--;
            float fraction=location-(float)floor_index;
            float delta=state[39+index]*fraction;
            float other=fraction-state[24];
            other=other*state[38+index];
            delta=delta-other;
            delta=delta-state[25];
            float coefficient=delta<0.0f ? state[8] : state[7];
            coefficient=filtered*state[9]+coefficient;
            float gain=coefficient*delta;
            gain=gain+state[25];
            state[25]=gain;
            float wet=gain*source;
            wet=wet*state[27];
            float asymmetric=wet<state[11] ? state[28] : 0.0f;
            asymmetric=asymmetric*wet;
            wet=asymmetric+wet;
            if (wet>=1.0f) wet=1.0f;
            else if (wet<=-1.0f) wet=-1.0f;
            filtered=state[29]*state[13];
            filtered=filtered+state[12]*wet;
            filtered=state[30]*state[14]+filtered;
            filtered=filtered-state[31]*state[15];
            filtered=filtered-state[32]*state[16];
            state[30]=state[29]; state[29]=wet; state[32]=state[31]; state[31]=filtered;
            float output=filtered*state[35];
            output=state[36]*output;
            output=state[37]*source+output;
            audio[i*channels+ch]=output;
        }
    }
    return 1;
}
