/* Independent Wwise FDN equations. No original executable bytes or CRT. */
typedef unsigned int u32;
typedef long long i64;
typedef long double E;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused=0;
#if defined(__x86_64__) || defined(_M_X64)
static E power(E base,E exponent){
 E value,integer,result;__asm__("fyl2x":"=t"(value):"0"(base),"u"(exponent):"st(1)");
 __asm__("frndint":"=t"(integer):"0"(value));E fraction=value-integer;
 __asm__("f2xm1":"=t"(result):"0"(fraction));result=result+1;
 __asm__("fscale":"=t"(result):"0"(result),"u"(integer));return result;
}
#else
static E power(E base,E exponent){return powl(base,exponent);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E logarithm(E x){E y;__asm__("fldln2; fxch; fyl2x":"=t"(y):"0"(x):"st(1)");return y;}
#else
static E logarithm(E x){return logl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E logten(E x){E y;__asm__("fldlg2; fxch; fyl2x":"=t"(y):"0"(x):"st(1)");return y;}
#else
static E logten(E x){return log10l(x);}
#endif
typedef struct {
 u32 count,channels,predelay,prepos,lengths[8],offsets[8],positions[8];
 float decay,damping,dry,wet,old_dry,old_wet,a[8],b[8],z[8],dc,previous_input,previous_delayed,dc_coef,shape_a,shape_b;
} Reverb;
static void coefficients(Reverb *r){
 E reciprocal=1/(E)48000;double inverse=(double)reciprocal;
 E ratio=1/(E)r->damping;double factor=(double)(1-1/(ratio*ratio));
 double constant=(double)(logarithm(10)*.25L);
 E maximum=power((E)(double).001,(E)r->lengths[r->count-1]*reciprocal/(E)r->decay);
 E value=logten(maximum)*(E)constant;
 if((E)factor*value>1)factor=(double)(1/value);
 for(u32 i=0;i<r->count;i++){
  E gain=power((E)(double).001,(E)r->lengths[i]*(E)inverse/(E)r->decay);
  E term=logten(gain)*(E)constant*(E)factor;
  r->a[i]=(float)((1-term)*gain);r->b[i]=(float)term;
 }
 E one=1/(E)r->damping;one=(1-one)/(one+1);E difference=1-one;
 r->shape_a=(float)(1/difference);r->shape_b=(float)((-1/difference)*one);
}
EXPORT u32 ft_reverb_abi(void){return 1;}
EXPORT u32 ft_reverb_state_size(void){return sizeof(Reverb);}
EXPORT int ft_reverb_initialize(Reverb *r,u32 count,u32 channels,const u32 *lengths,u32 predelay,const float *values){
 if(!r||!lengths||!values||(count!=4&&count!=8)||(channels!=1&&channels!=2))return 0;
 for(u32 i=0;i<sizeof(Reverb);i++)((unsigned char*)r)[i]=0;
 r->count=count;r->channels=channels;r->predelay=predelay;
 u32 offset=0;for(u32 i=0;i<count;i++){if(lengths[i]<1)return 0;r->lengths[i]=lengths[i];r->offsets[i]=offset;offset+=lengths[i];}
 r->decay=values[0];r->damping=values[1];r->dry=values[2];r->wet=values[3];r->old_dry=values[4];r->old_wet=values[5];
 r->dc_coef=1.0f-62.831856f/48000.0f;coefficients(r);return 1;
}
EXPORT int ft_reverb_parameter(Reverb *r,u32 identity,float value){
 if(!r)return 0;
 if(identity==0)r->decay=value;else if(identity==1)r->damping=value;
 else if(identity==3)r->dry=value;else if(identity==4)r->wet=value;else return 0;
 if(identity<2)coefficients(r);return 1;
}
EXPORT int ft_reverb_reset(Reverb *r,float *rings,float *pre){
 if(!r||!rings||!pre)return 0;
 for(u32 j=0;j<r->count;j++){for(u32 i=0;i<r->lengths[j];i++)rings[r->offsets[j]+i]=0;r->z[j]=0;}
 for(u32 i=0;i<r->predelay;i++)pre[i]=0;
 r->dc=r->previous_input=r->previous_delayed=0;return 1;
}
EXPORT int ft_reverb_process(Reverb *r,float *rings,float *pre,float *audio){
 if(!r||!rings||!pre||!audio)return 0;
 float dry=r->old_dry,wet=r->old_wet,ds=(r->dry-dry)/128.0f,ws=(r->wet-wet)/128.0f;
 for(u32 frame=0;frame<128;frame++){
  float z[8],paired[4];for(u32 j=0;j<r->count;j++){float read=rings[r->offsets[j]+r->positions[j]];z[j]=r->z[j]*r->b[j]+read*r->a[j];r->z[j]=z[j];}
  for(u32 j=0;j<4;j++)paired[j]=r->count==4?z[j]:z[j+4]+z[j];
  float sum=(paired[3]+paired[1])+(paired[2]+paired[0]);
  float left=(-paired[3]-paired[1])+(paired[2]+paired[0]);
  float right=(-paired[3]+paired[1])+(-paired[2]+paired[0]);
  float input=audio[frame*r->channels];if(r->channels==2)input=input+audio[frame*2+1];
  dry=dry+ds;wet=wet+ws;
  audio[frame*r->channels]=audio[frame*r->channels]*dry+left*wet;
  if(r->channels==2)audio[frame*2+1]=audio[frame*2+1]*dry+right*wet;
  r->dc=(r->dc_coef*r->dc+input)-r->previous_input;r->previous_input=input;
  float delayed=r->dc;if(r->predelay){delayed=pre[r->prepos];pre[r->prepos]=r->dc;r->prepos++;if(r->prepos==r->predelay)r->prepos=0;}
  float shaped=r->shape_a*delayed+r->shape_b*r->previous_delayed;r->previous_delayed=delayed;
  float scale=sum*(-2.0f/(float)r->count);
  for(u32 j=0;j<r->count;j++){
   rings[r->offsets[j]+r->positions[j]]=shaped+(scale+z[(j+1)%r->count]);
   if(++r->positions[j]==r->lengths[j])r->positions[j]=0;
  }
 }
 r->old_dry=r->dry;r->old_wet=r->wet;return 1;
}
