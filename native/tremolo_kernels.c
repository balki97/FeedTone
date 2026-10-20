/* Independent equations; original executable code is never loaded. */
typedef unsigned int U;
typedef long double E;
int _fltused;
#include "portable.h"
#define API FT_EXPORT

static float sine(float x) {
    float xx=x*x;
    float y=0.008306325f-xx*0.00018363654f;
    y=y*xx-0.16664828f;
    y=y*xx+0.9999966f;
    return y*x;
}

static U segment(float boundary,float phase,float inverse,U remaining) {
    E value=(E)(double)(((E)boundary-(E)phase)*(E)inverse);
    long long count=(long long)value;
    if((E)count<value)count++;
    if(count<=0)return 0;
    return (E)count<remaining?(U)count:remaining;
}

API int ft_tremolo(float *audio,U frames,U channels,float *phases,float *smooth,U wave,
                    float step,float b,float a,float duty,float previous_depth,float depth,
                    float previous_gain,float gain) {
    if(!audio||!phases||!smooth||frames!=128||(channels!=1&&channels!=2)||wave>2)return 0;
    const float period=6.2831854820251465f,pi=3.1415927410125732f,half_pi=1.5707963705062866f;
    float increment=step>1e-8f?step:1e-8f;
    float depth_step=(depth-previous_depth)/(float)frames;
    float gain_step=(gain-previous_gain)/(float)frames;
    for(U c=0;c<channels;c++){
        float phase=phases[c],smoothed=smooth[c],d=previous_depth,g=gain;
        U i=0;float inverse=1.f/increment;
        while(i<frames){
            U sections=wave?2:4;
            for(U section=0;section<sections&&i<frames;section++){
                float boundary=wave?(section==0?(wave==1?.5f:duty):1.f):section==0?half_pi:section==1?pi:section==2?pi+half_pi:period;
                U n=segment(boundary,phase,inverse,frames-i);
                for(U j=0;j<n;j++){
                    phase=phase+increment;d=d+depth_step;g=g+gain_step;
                    float level;
                    if(wave==0){
                        float angle=section==0?phase:section==1?pi-phase:section==2?phase-pi:period-phase;
                        float value=sine(angle);if(section>=2)value=-value;
                        value=(value+1.f)*.5f;level=value*d+(1.f-d);
                    }else{
                        float value=wave==1?(section==0?phase*2.f:(1.f-phase)*2.f):(section==0?1.f:0.f);
                        smoothed=(value*d)*b-a*smoothed;level=(1.f-d)+smoothed;
                    }
                    audio[i*channels+c]=(level*g)*audio[i*channels+c];i++;
                }
            }
            float limit=wave?1.f:period;
            if(phase>=limit)phase=phase-limit;
        }
        if(step!=0){phases[c]=phase;smooth[c]=smoothed;}
    }
    return 1;
}
