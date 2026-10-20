/* Independent source RoomVerb equations; no original machine code or CRT. */
typedef unsigned int u32;typedef long double E;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused=0;
#if defined(__x86_64__) || defined(_M_X64)
static E power(E x,E y){E v,n,r;__asm__("fyl2x":"=t"(v):"0"(x),"u"(y):"st(1)");__asm__("frndint":"=t"(n):"0"(v));E f=v-n;__asm__("f2xm1":"=t"(r):"0"(f));r=r+1;__asm__("fscale":"=t"(r):"0"(r),"u"(n));return r;}
#else
static E power(E x,E y){return powl(x,y);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E root(E x){E y;__asm__("fsqrt":"=t"(y):"0"(x));return y;}
#else
static E root(E x){return sqrtl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E ln(E x){E y;__asm__("fldln2; fxch; fyl2x":"=t"(y):"0"(x):"st(1)");return y;}
#else
static E ln(E x){return logl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E logten(E x){E y;__asm__("fldlg2; fxch; fyl2x":"=t"(y):"0"(x):"st(1)");return y;}
#else
static E logten(E x){return log10l(x);}
#endif
typedef struct{u32 length,offset,position;float gain;} Ring;
typedef struct{Ring rings[4],extra;float a[4],b[4],z[4];} Unit;
typedef struct{
 u32 channels,count,total,tap_count[2],tap_initial[2][64],tap_positions[2][64];
 float tap_gain[2][64];Ring allpass[4],early_input,late_input,early_ring;Unit units[4];
 float decay,damping,diffusion,old_mix[3],mix[3],width_a,width_b,mono_gain,normalization,dc_coefficient,dc_state[2][2],scratch[13][128];
} Room;
static void coefficient(Unit *u,float decay,float damping){
 double factor=(double)(1-(E)damping*(E)damping);
 E g=power(10,(E)u->rings[3].length*(E)(double)-3.0/((E)decay*48000));
 E term=logten(g)*20;term=term*ln(10);term=term*(E)(double).0125;
 float effective=(float)root(term*(E)factor>1?1-1/term:1-(E)factor);
 for(u32 j=0;j<4;j++){
  g=power(10,(E)u->rings[j].length*(E)(double)-3.0/((E)decay*48000));
  term=logten(g)*20;term=term*ln(10);term=term*(E)(double).0125;term=term*(1-(E)effective*(E)effective);
  if(term>(E)(double).999)term=(E)(double).999;
  u->a[j]=(float)((1-term)*g);u->b[j]=(float)-term;
 }
}
static void diffusion(Room *r,float value){
 float delta[4]={1.85409f,1.23606f,.61803f,0};r->diffusion=value;
 for(u32 j=0;j<4;j++){float gain=value*.01f;gain=gain*.61803f;gain=gain*4.0f;gain=gain-delta[j];if(gain<0)gain=0;if(gain>=.61803f)gain=.61803f;r->allpass[j].gain=gain;}
}
static void configure_ring(Ring *r,u32 length,u32 *total,u32 factor){r->length=length;r->offset=*total;r->position=0;*total+=length*factor;}
EXPORT u32 ft_room_abi(void){return 1;}
EXPORT u32 ft_room_state_size(void){return sizeof(Room);}
/* Integer config: channels,count,allpass[4],early_input,late_input,er_length,
   tap_count[2],tap_positions[128],fdn_lengths[16],extra_lengths[4].
   Float config: decay,damping,diffusion,dry,early,late,width,normalization,dc,
                 mono center input gain,allpass initial gains[4],tap_gains[128]. */
EXPORT int ft_room_initialize(Room *r,const u32 *c,const float *v){
 if(!r||!c||!v||c[0]<1||c[0]>2||c[1]<1||c[1]>4)return 0;
 for(u32 i=0;i<sizeof(Room);i++)((unsigned char*)r)[i]=0;
 r->channels=c[0];r->count=c[1];r->decay=v[0];r->damping=v[1];r->diffusion=v[2];
 for(u32 j=0;j<3;j++)r->old_mix[j]=r->mix[j]=v[3+j];
 r->width_a=v[6]*.0055555557f;r->width_a=r->width_a*.292894f;r->width_a=r->width_a+.707106f;
 float balance=1.0f-r->width_a*r->width_a;r->width_b=balance>0?(float)root((E)balance):0;
 r->normalization=v[7];r->dc_coefficient=v[8];
 float center=v[9];float square=center*center;r->mono_gain=(float)root((E)(float)(1.0f/square));r->mono_gain=r->mono_gain*center;
 u32 total=0;
 for(u32 j=0;j<4;j++){
  configure_ring(&r->allpass[j],c[2+j],&total,2);
  E gain=(E)v[2]*(E)(float).01f*(E)(float).61803f*4-(E)(3-j)*(E)(float).61803f;
  float rounded=(float)gain;if(gain<=0)rounded=0;if(rounded>=.61803f)rounded=.61803f;r->allpass[j].gain=rounded;
 }
 configure_ring(&r->early_input,c[6],&total,1);configure_ring(&r->late_input,c[7],&total,1);configure_ring(&r->early_ring,c[8],&total,1);
 for(u32 side=0;side<2;side++){
  r->tap_count[side]=c[9+side];if(r->tap_count[side]>64)return 0;
  for(u32 j=0;j<r->tap_count[side];j++){u32 pos=c[11+side*64+j];if(pos>=c[8])return 0;r->tap_initial[side][j]=r->tap_positions[side][j]=pos;r->tap_gain[side][j]=v[14+side*64+j];}
 }
 for(u32 u=0;u<r->count;u++){
  for(u32 j=0;j<4;j++)configure_ring(&r->units[u].rings[j],c[139+u*4+j],&total,1);
  configure_ring(&r->units[u].extra,c[155+u],&total,1);coefficient(&r->units[u],r->decay,r->damping);
 }
 r->total=total;return 1;
}
EXPORT u32 ft_room_total(Room *r){return r?r->total:0;}
EXPORT int ft_room_parameter(Room *r,u32 id,float value){
 if(!r)return 0;
 if(id==10||id==11){if(id==10)r->decay=value;else r->damping=value;for(u32 u=0;u<r->count;u++)coefficient(&r->units[u],r->decay,r->damping);}
 else if(id==15)diffusion(r,value);else if(id>=60&&id<=62)r->mix[id-60]=value;else return 0;
 return 1;
}
static void delay(Ring *r,float *memory,float *samples){
 if(!r->length)return;
 for(u32 i=0;i<128;i++){float old=memory[r->offset+r->position];memory[r->offset+r->position]=samples[i];samples[i]=old;if(++r->position==r->length)r->position=0;}
}
static void allpass(Ring *r,float *memory,float *samples){
 for(u32 i=0;i<128;i++){u32 at=r->offset+r->position*2;float input=samples[i],old=memory[at];float out=(input-memory[at+1])*r->gain+old;memory[at]=input;memory[at+1]=out;samples[i]=out;if(++r->position==r->length)r->position=0;}
}
static void fdn(Unit *u,float *memory,const float *input,float *output){
 u32 done=0;
 while(done<128){u32 chunk=128-done;for(u32 j=0;j<4;j++){u32 remaining=u->rings[j].length-u->rings[j].position;if(remaining<chunk)chunk=remaining;}
  u32 vector_count=chunk&~3U;
  for(u32 i=0;i<chunk;i++){
   float y[4];for(u32 j=0;j<4;j++){Ring *r=&u->rings[j];float read=memory[r->offset+r->position];y[j]=read*u->a[j]+(-u->b[j])*u->z[j];u->z[j]=y[j];}
   float common;
   if(i<vector_count){output[done+i]=((y[0]+y[2])+output[done+i])-(y[1]+y[3]);common=(((y[0]+y[1])+y[2])+y[3])*(-.5f)+input[done+i];}
   else{output[done+i]=output[done+i]+((-y[3]-y[1])+(y[2]+y[0]));common=(y[3]*-.5f+y[1]*-.5f)+(y[2]*-.5f+y[0]*-.5f);}
   for(u32 j=0;j<4;j++){Ring *r=&u->rings[j];float write=common+y[(j+1)&3];if(i>=vector_count)write=write+input[done+i];memory[r->offset+r->position]=write;r->position++;}
  }
  for(u32 j=0;j<4;j++)if(u->rings[j].position==u->rings[j].length)u->rings[j].position=0;
  done+=chunk;
 }
}
static void ramp(float start,float end,float *values){float step=(end-start)/128.0f,value=start;for(u32 i=0;i<128;i++){values[i]=value;value=value+step;}}
EXPORT int ft_room_reset(Room *r,float *memory){
 if(!r||!memory)return 0;for(u32 i=0;i<r->total;i++)memory[i]=0;
 for(u32 u=0;u<r->count;u++)for(u32 j=0;j<4;j++)r->units[u].z[j]=0;
 for(u32 side=0;side<2;side++)r->dc_state[side][0]=r->dc_state[side][1]=0;
 return 1;
}
EXPORT int ft_room_process(Room *r,float *memory,float *audio){
 if(!r||!memory||!audio)return 0;
 float *input=r->scratch[0],*late=r->scratch[1],(*early)[128]=&r->scratch[2],(*out)[128]=&r->scratch[4];
 for(u32 i=0;i<128;i++){input[i]=audio[i*r->channels]*r->mono_gain;if(r->channels==2){input[i]=audio[i*2]*.7071067690849304f;input[i]=input[i]+audio[i*2+1]*.7071067690849304f;}late[i]=input[i];out[0][i]=out[1][i]=0;}
 delay(&r->late_input,memory,late);delay(&r->early_input,memory,input);
 for(u32 i=0;i<128;i++){
  Ring *er=&r->early_ring;memory[er->offset+er->position]=input[i];
  for(u32 side=0;side<2;side++){float sum=0;for(u32 j=0;j<r->tap_count[side];j++){u32 pos=r->tap_positions[side][j];sum=memory[er->offset+pos]*r->tap_gain[side][j]+sum;if(++pos==er->length)pos=0;r->tap_positions[side][j]=pos;}early[side][i]=sum;}
  if(++er->position==er->length)er->position=0;
 }
 for(u32 j=0;j<4;j++)allpass(&r->allpass[j],memory,late);
 for(u32 u=0;u<r->count;u++){delay(&r->units[u].extra,memory,late);fdn(&r->units[u],memory,late,out[u&1]);}
 float normalization=r->normalization*1.4142135f;
 for(u32 side=0;side<2;side++)for(u32 i=0;i<128;i++){float value=out[side][i]*normalization;float result=r->dc_state[side][1]*r->dc_coefficient+(value-r->dc_state[side][0]);r->dc_state[side][0]=value;r->dc_state[side][1]=result;out[side][i]=result;}
 float (*gain)[128]=&r->scratch[6];for(u32 j=0;j<3;j++)ramp(r->old_mix[j],r->mix[j],gain[j]);
 float (*late_gain)[128]=&r->scratch[9],(*early_gain)[128]=&r->scratch[11];
 float wa[2]={r->width_a,r->width_b};
 for(u32 side=0;side<2;side++){
  float w=r->channels==1?.707106f:wa[side];
  ramp(r->old_mix[2]*w,r->mix[2]*w,late_gain[side]);ramp(r->old_mix[1]*w,r->mix[1]*w,early_gain[side]);
 }
 for(u32 i=0;i<128;i++)for(u32 ch=0;ch<r->channels;ch++){
  u32 a=ch,b=ch^1;float result=(audio[i*r->channels+ch]*gain[0][i]+out[0][i]*late_gain[a][i])+out[1][i]*late_gain[b][i];
  result=(result+early[0][i]*early_gain[a][i])+early[1][i]*early_gain[b][i];audio[i*r->channels+ch]=result;
 }
 for(u32 j=0;j<3;j++)r->old_mix[j]=r->mix[j];return 1;
}
