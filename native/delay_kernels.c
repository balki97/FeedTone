/* Independent source reconstruction of 0x41033; no original executable bytes. */
typedef unsigned int u32;
typedef long long i64;
typedef long double E;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused=0;
#if defined(__x86_64__) || defined(_M_X64)
static E sine(E x){E y;__asm__("fsin":"=t"(y):"0"(x));return y;}
#else
static E sine(E x){return sinl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E cosine(E x){E y;__asm__("fcos":"=t"(y):"0"(x));return y;}
#else
static E cosine(E x){return cosl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E arctan(E x){E y;__asm__("fld1; fpatan":"=t"(y):"0"(x):"st(1)");return y;}
#else
static E arctan(E x){return atanl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static E power(E base,E exponent){
    if(base==0)return 0;
    E value,integer,fraction,result;
    __asm__("fyl2x":"=t"(value):"0"(base),"u"(exponent):"st(1)");
    __asm__("frndint":"=t"(integer):"0"(value));
    fraction=value-integer;
    __asm__("f2xm1":"=t"(result):"0"(fraction));
    result=result+1;
    __asm__("fscale":"=t"(result):"0"(result),"u"(integer));
    return result;
}
#else
static E power(E base,E exponent){return powl(base,exponent);}
#endif
static float exponential(float x){return (float)power(2.7182818284590452353602874713526625L,(E)x);}
static u32 round_positive(E x){return (u32)(i64)(x+.5L);}

typedef struct {double c[5],s[2];} IIR;
typedef struct {
    u32 rate,model,n,write,length,avg_n,avg_pos,dither,mask;
    float p[9],current,read,phase,depth,average[8],average_sum;
    float input_gain,wet_gain,colour_a,colour_b,normal,saturation,gamma;
    IIR filters[3];
} Delay;

static void filter_config(IIR *filter,u32 rate,float frequency,float q,u32 high){
    E angle=(E)(double)6.283185307179586476925286766559L*(E)frequency/(E)rate;
    double c=(double)cosine((E)(double)angle);
    E alpha=sine((E)(double)angle)/((E)q+(E)q);
    double a0=(double)(1+alpha), a1=(double)((E)c*-2),a2=(double)(1-alpha);
    double sum=(double)(high?1+(E)c:1-(E)c);
    double b0=(double)((E)sum*.5L),b1=high?-sum:sum;
    filter->c[0]=(double)((E)b0/(E)a0);filter->c[1]=(double)((E)b1/(E)a0);
    filter->c[2]=filter->c[0];filter->c[3]=(double)((E)a1/(E)a0);filter->c[4]=(double)((E)a2/(E)a0);
    filter->s[0]=filter->s[1]=0;
}
static float filtered(IIR *filter,float input){
    E out=(E)filter->c[0]*(E)input+(E)filter->s[0];
    filter->s[0]=(double)(((E)filter->c[1]*(E)input+(E)filter->s[1])-(E)filter->c[3]*out);
    E state=(E)filter->c[2]*(E)input-(E)filter->c[4]*out+(E)(float)1e-10f;
    filter->s[1]=(state>-(E)(float)1e-10f&&state<(E)(float)1e-10f)?0:(double)state;
    return (float)out;
}
static void modulation(Delay *d){
    float period=d->model==1?333.0f:d->model==2?750.0f:500.0f;
    float depth=d->model<=2?.1f:0;
    if(depth>d->current)depth=d->current;
    d->phase=(float)((E)(float)6.2831855f/((E)d->rate*(E)period*(E)(double)0.0010000000474974513));
    d->depth=(float)((E)depth*(E)(double)0.0010000000474974513*(E)d->rate);
}
static void colour(Delay *d){
    float value=d->p[8];
    d->colour_a=(float)((E)value*(E)(double)1.14+(E)(double).1);
    d->normal=(float)sine((E)(float)((E)d->colour_a*(E)(double)1.5707963705062866));
    d->colour_b=(float)((E)value*(E)(double).61+(E)(double).01);
    d->saturation=exponential((float)((E)(float)((E)value*(E)(double)1.7999999523162842)*(E)(double).115129254758358));
    d->gamma=(float)((E)value*(E)(double)6.5+1);
    d->input_gain=d->model==2?exponential((float)((E)(float)((E)value*20)*(E)(double).115129254758358)):1;
    d->wet_gain=d->model==2?(float)(1-(E)value*.5L):1;
    u32 bits=round_positive((E)(float)(16-(E)value*10));
    if(bits<6)bits=6;if(bits>24)bits=24;
    d->mask=0xffffffffU<<(32-bits);
    d->avg_n=d->model>=3?round_positive((E)(float)((E)value*8)):0;
    if(d->avg_n>8)d->avg_n=8;
    for(u32 i=0;i<8;i++)d->average[i]=0;
    d->avg_pos=0;d->average_sum=0;
}
static void model(Delay *d,u32 identity){
    d->model=identity;
    float frequency=identity==0?5500:identity==1?4000:identity==2?1500:1865;
    float q=identity==0?.38f:identity==1?.59f:identity==2?.9f:.53f;
    filter_config(&d->filters[0],d->rate,frequency,q,0);
    modulation(d);colour(d);
}
static void reset(Delay *d,float *ring){
    for(u32 i=0;i<d->length;i++)ring[i]=0;
    for(u32 i=0;i<3;i++)d->filters[i].s[0]=d->filters[i].s[1]=0;
    d->n=0;d->read=0;d->current=d->p[6];
    if(d->current<40)d->current=40;if(d->current>1000)d->current=1000;
    d->write=round_positive((E)(float)((E)d->current*(E)(double)0.0010000000474974513*(E)d->rate))+1;
    colour(d);
}
EXPORT u32 ft_delay_abi(void){return 1;}
EXPORT u32 ft_delay_state_size(void){return sizeof(Delay);}
EXPORT int ft_delay_initialize(Delay *d,float *ring,u32 length,u32 rate){
    if(!d||!ring||rate!=48000||length!=96001)return 0;
    unsigned char *bytes=(unsigned char*)d;for(u32 i=0;i<sizeof(Delay);i++)bytes[i]=0;
    d->rate=rate;d->length=length;
    float defaults[9]={100,0,80,.2f,10000,.2f,200,20,.25f};
    for(u32 i=0;i<9;i++)d->p[i]=defaults[i];
    filter_config(&d->filters[1],rate,80,.2f,1);filter_config(&d->filters[2],rate,10000,.2f,0);
    model(d,0);reset(d,ring);return 1;
}
EXPORT int ft_delay_parameter(Delay *d,u32 identity,float value){
    if(!d||identity>9)return 0;
    if(identity==9){if(value<0||value>3||value!=(u32)value)return 0;if(d->model!=(u32)value)model(d,(u32)value);return 1;}
    /* The original core ignores frequencies below20Hz, including authored log-curve rounding. */
    if((identity==2||identity==4)&&(value<20.0f||value>20000.0f))return 1;
    if(d->p[identity]==value)return 1;
    d->p[identity]=value;
    if(identity==2||identity==3)filter_config(&d->filters[1],d->rate,d->p[2],d->p[3],1);
    if(identity==4||identity==5)filter_config(&d->filters[2],d->rate,d->p[4],d->p[5],0);
    if(identity==8)colour(d);
    return 1;
}
EXPORT int ft_delay_reset(Delay *d,float *ring){if(!d||!ring)return 0;reset(d,ring);return 1;}

EXPORT int ft_delay_process(Delay *d,float *ring,float *audio,u32 frames){
    if(!d||!ring||!audio||frames>128)return 0;
    for(u32 i=0;i<frames;i++){
        float argument=(float)((E)d->n*(E)d->phase);d->n++;
        float wave=(float)sine((E)argument);
        float at=(float)((E)wave*(E)d->depth+(E)d->read);
        if(at<0){at=(float)((E)d->length+(E)at);if(at<0)at=0;}
        i64 index=(i64)(E)at;
        float fraction=(float)((E)at-(E)index),square=(float)((E)fraction*(E)fraction);
        u32 ix[4];
        for(u32 j=0;j<4;j++){i64 position=index+(i64)j-1;if(position<0)position+=d->length;ix[j]=position<0?0:(u32)(position%d->length);}
        float y0=ring[ix[0]],y1=ring[ix[1]],y2=ring[ix[2]],y3=ring[ix[3]];
        float p=(float)((E)y1+(((E)y3-(E)y2)-(E)y0));
        float c=(float)(((E)y0-(E)y1)-(E)p);
        float difference=(float)((E)y2-(E)y0);
        E cubic=(E)square*(E)c+((E)p*(E)fraction)*(E)square;
        float delayed=(float)((E)y1+((E)difference*(E)fraction+cubic));
        d->read=(float)((E)d->read+1);
        if(d->read>(float)(d->length-1))d->read=(float)((E)d->read-(E)(d->length-1));
        float value=(float)((E)delayed*(E)(float)((E)d->p[7]/100)+(E)audio[i]*(E)d->input_gain);
        if(d->model==0||d->model==1){
            float factor=d->model==0?d->colour_a:d->colour_b;
            float z=(float)((E)value*(E)(double)3.1415927410125732*(E)(double).5*(E)factor);
            value=(float)((E)(float)sine((E)z)/(E)d->normal);
            if(d->model==1&&d->saturation!=1){
                value=(float)((E)d->saturation*(E)value);
                value=value<=0?(float)(1/(1-(E)value)-1):(float)(1-1/((E)value+1));
            }
        }else if(d->model==2){
            float magnitude=value<0?-value:value,sign=value<0?1:-1;
            float a=(float)power((E)magnitude,(E)d->gamma);
            a=(float)arctan((E)a);
            value=(float)((E)(float)power((E)a,(E)(float)(1/(E)d->gamma))*(E)sign);
        }else{
            if(d->avg_n){
                d->average_sum=(float)((E)d->average_sum+(E)value);
                d->average_sum=(float)((E)d->average_sum-(E)d->average[d->avg_pos]);
                d->average[d->avg_pos]=value;d->avg_pos=(d->avg_pos+1)%d->avg_n;
                value=(float)((E)d->average_sum/(E)d->avg_n);
            }
            if(value>1)value=1;if(value< -1)value=-1;
            float sign=value<0?-1:1,absolute=value<0?-value:value;
            u32 code=(u32)(i64)((E)absolute*(E)(double)2147483647.0);
            value=(float)((E)(int)(code&d->mask)*(E)sign*(E)(double)4.656612873077393e-10);
            value=(float)((E)value+(d->dither&128?(E)(double)1e-10:-(E)(double)1e-10));d->dither=(d->dither+1)&255;
        }
        value=filtered(&d->filters[0],value);value=filtered(&d->filters[1],value);value=filtered(&d->filters[2],value);
        ring[d->write]=value;d->write=(d->write+1)%d->length;
        audio[i]=(float)((E)(float)((E)d->p[0]/100)*(E)audio[i]+(E)d->wet_gain*(E)(float)((E)d->p[1]/100)*(E)delayed);
        float target=d->p[6];if(target<40)target=40;if(target>1000)target=1000;
        if(target!=d->current){
            float step=(float)((E)target-(E)d->current),distance=(float)((E)d->rate*(E)step*(E)(double)0.0010000000474974513);
            if(distance>1||distance< -1)step=(float)(1000/(E)d->rate)*(step<0?-1:1);
            d->current=(float)((E)d->current+(E)step);
            u32 lag=round_positive((E)(float)((E)d->current*(E)(double)0.0010000000474974513*(E)d->rate));
            d->read=(float)((E)d->write-(E)(lag+1));if(d->read<0)d->read=(float)((E)d->read+(E)d->length);
            modulation(d);
        }
    }
    return 1;
}
