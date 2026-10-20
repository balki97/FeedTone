/* Independently implemented chorus delay, bipolar oscillator and mix equations. */
typedef unsigned int U;
typedef long double E;
int _fltused;
#include "portable.h"
#define API FT_EXPORT
typedef struct {U position;float feedback,forward,direct,phase,smooth;} Channel;
static float sine(float x){float s=x*x;float y=.008306325f-s*.00018363654f;y=y*s-.16664828f;y=y*s+.9999966f;return y*x;}
static U segment(float boundary,float phase,float inverse,U remaining){
 E value=(E)(double)(((E)boundary-(E)phase)*(E)inverse);
 long long count=(long long)value;if((E)count<value)count++;
 if(count<=0)return 0;return (E)count<remaining?(U)count:remaining;
}
API int ft_chorus(float *audio,float *ring,Channel *s,U frames,U length,U delay,U extent,
                  float feedback,float forward,float direct,float step,float b,float a,
                  float duty,U wave,float old_depth,float depth,U enabled,
                  float old_wet,float wet,float old_dry,float dry){
 if(!audio||!ring||!s||frames!=128||length!=delay*2+1024||wave>2)return 0;
 float modulation[128],input[128];
 float increment=step>1e-8f?step:1e-8f,phase=s->phase,smoothed=s->smooth;
 float depth_step=(depth-old_depth)/frames,amplitude=old_depth;
 const float pi=3.1415927410125732f,period=6.2831854820251465f,half=1.5707963705062866f;
 for(U i=0;i<frames;i++)input[i]=audio[i];
 if(enabled){U i=0;float inverse=1.f/increment;
  while(i<frames){
   U sections=wave?2:4;
   for(U section=0;section<sections&&i<frames;section++){
    float boundary=wave?(section==0?(wave==1?.5f:duty):1.f):section==0?half:section==1?pi:section==2?pi+half:period;
    U n=segment(boundary,phase,inverse,frames-i);
    for(U j=0;j<n;j++){
     phase=phase+increment;amplitude=amplitude+depth_step;
     if(wave==0){float angle=section==0?phase:section==1?pi-phase:section==2?phase-pi:period-phase;float value=sine(angle)*amplitude;modulation[i++]=section>=2?-value:value;}
     else {float value=wave==1?(section==0?phase*4.f-1.f:(1.f-phase)*4.f-1.f):(section==0?1.f:-1.f);smoothed=(value*amplitude)*b-a*smoothed;modulation[i++]=smoothed;}
   }}
   float limit=wave?1.f:period;if(phase>=limit)phase=phase-limit;
  }
 }
 if(enabled&&step!=0){s->phase=phase;s->smooth=smoothed;}
 float fb=s->feedback,ff=s->forward,di=s->direct;
 float fb_step=(feedback-fb)/frames,ff_step=(forward-ff)/frames,di_step=(direct-di)/frames;
 U pos=s->position,off=length-delay,at=0;
 while(at<frames){
  U read=(off+pos)%length,n=1,fast=0;
  if(enabled){
   U bound=(length-extent)-1,span=(length-pos)-1;
   if(bound-read<span)span=bound-read;if(frames-at<span)span=frames-at;
   if(read<bound&&read>=extent&&pos!=length-1&&span>=8){fast=1;n=(span>>3)<<3;}
  }
  for(U k=0;k<n;k++){
   float delayed;
   if(enabled){
    U base=fast?read+k:off+pos;
    E location=(E)base+(E)extent*(E)modulation[at];U index=(U)(long long)location;
    float fraction=(float)(location-(E)index);
    delayed=(1.f-fraction)*ring[index%length]+ring[(index+1)%length]*fraction;
   }else delayed=ring[(off+pos)%length];
   fb=fb+fb_step;ff=ff+ff_step;di=di+di_step;
   float value=delayed*fb+audio[at];ring[pos]=value;
   audio[at]=value*di+delayed*ff;
   pos=(pos+1)%length;at++;
  }
 }
 s->position=pos;s->feedback=feedback;s->forward=forward;s->direct=direct;
 float ws=(wet-old_wet)/frames,ds=(dry-old_dry)/frames,w=old_wet,d=old_dry;
 if(wet==old_wet&&dry==old_dry){for(U i=0;i<frames;i++)audio[i]=input[i]*dry+audio[i]*wet;}
 else for(U i=0;i<frames;i++){
  audio[i]=audio[i]*w+input[i]*d;w=ws+w;d=ds+d;
 }
 return 1;
}
