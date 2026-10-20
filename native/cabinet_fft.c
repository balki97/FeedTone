/* Independent fixed-size real FFT and spectral cabinet equations. */
typedef unsigned int U;
typedef struct {float r,i;} Complex;
int _fltused;
#include "portable.h"
#define API FT_EXPORT

#if defined(__x86_64__) || defined(_M_X64)
static long double cos80(long double x){long double y;__asm__("fcos":"=t"(y):"0"(x));return y;}
#else
static long double cos80(long double x){return cosl(x);}
#endif
#if defined(__x86_64__) || defined(_M_X64)
static long double sin80(long double x){long double y;__asm__("fsin":"=t"(y):"0"(x));return y;}
#else
static long double sin80(long double x){return sinl(x);}
#endif
static Complex add(Complex a,Complex b){Complex c={a.r+b.r,a.i+b.i};return c;}
static Complex sub(Complex a,Complex b){Complex c={a.r-b.r,a.i-b.i};return c;}
static Complex mul(Complex a,Complex b){float rr=a.r*b.r,ii=a.i*b.i,ri=a.r*b.i,ir=a.i*b.r;Complex c={rr-ii,ir+ri};return c;}
static Complex conj(Complex a){a.i=-a.i;return a;}

API int ft_cab_tables(Complex *forward,Complex *inverse,Complex *super_forward,Complex *super_inverse){
    if(!forward||!inverse||!super_forward||!super_inverse)return 0;
    const long double tau=(long double)(double)6.283185307179586;
    const long double pi=(long double)(double)3.141592653589793;
    for(U k=0;k<128;k++){
        long double a=(long double)k*tau/128.L;
        forward[k].r=(float)cos80(-a);forward[k].i=(float)sin80(-a);
        inverse[k].r=(float)cos80(a);inverse[k].i=(float)sin80(a);
    }
    for(U k=0;k<64;k++){
        long double a=((long double)(k+1)/128.L+.5L)*pi;
        super_forward[k].r=(float)cos80(-a);super_forward[k].i=(float)sin80(-a);
        super_inverse[k].r=(float)cos80(a);super_inverse[k].i=(float)sin80(a);
    }
    return 1;
}

static void complex_fft(Complex *out,const Complex *input,U stride,U size,const Complex *twiddle,U inverse){
    U radix=size==2?2:4,m=size/radix;
    if(m==1){for(U j=0;j<radix;j++)out[j]=input[j*stride];}
    else for(U j=0;j<radix;j++)complex_fft(out+j*m,input+j*stride,stride*radix,m,twiddle,inverse);
    if(radix==2){Complex a=out[0],b=out[1];out[1]=sub(a,b);out[0]=add(a,b);return;}
    for(U k=0;k<m;k++){
        Complex s0=out[k],s1=mul(out[k+m],twiddle[k*stride]);
        Complex s2=mul(out[k+2*m],twiddle[k*stride*2]),s3=mul(out[k+3*m],twiddle[k*stride*3]);
        Complex a=add(s2,s0),b=sub(s0,s2),c=add(s3,s1),d=sub(s1,s3);
        out[k]=add(c,a);out[k+2*m]=sub(a,c);
        if(!inverse){
            Complex one={b.r+d.i,b.i-d.r},three={b.r-d.i,b.i+d.r};
            out[k+m]=one;out[k+3*m]=three;
        }else{
            Complex one={b.r-d.i,b.i+d.r},three={b.r+d.i,b.i-d.r};
            out[k+m]=one;out[k+3*m]=three;
        }
    }
}

API int ft_cab_forward(const float *input,Complex *output,Complex *temporary,const Complex *twiddle,const Complex *super){
    if(!input||!output||!temporary||!twiddle||!super)return 0;
    complex_fft(temporary,(const Complex*)input,1,128,twiddle,0);
    for(U k=1;k<=64;k++){
        Complex fk=temporary[k],fn=conj(temporary[128-k]);
        Complex even=add(fn,fk),odd=mul(sub(fk,fn),super[k-1]);
        Complex a=add(odd,even),b=conj(sub(even,odd));
        a.r=a.r*.5f;a.i=a.i*.5f;b.r=b.r*.5f;b.i=b.i*.5f;
        output[k]=a;output[128-k]=b;
    }
    output[0].r=temporary[0].i+temporary[0].r;output[0].i=0;
    output[128].r=temporary[0].r-temporary[0].i;output[128].i=0;
    return 1;
}

API int ft_cab_inverse(const Complex *input,float *output,Complex *temporary,const Complex *twiddle,const Complex *super){
    if(!input||!output||!temporary||!twiddle||!super)return 0;
    temporary[0].r=input[0].r+input[128].r;
    temporary[0].i=input[0].r-input[128].r;
    for(U k=1;k<=64;k++){
        Complex fk=input[k],fn=conj(input[128-k]);
        Complex even=add(fn,fk),odd=mul(sub(fk,fn),super[k-1]);
        temporary[k]=add(odd,even);temporary[128-k]=conj(sub(even,odd));
    }
    complex_fft((Complex*)output,temporary,1,128,twiddle,1);
    return 1;
}

API int ft_cab_process(const float *input,float *output,const Complex *spectra,Complex *ring,U partitions,U *position,
                       const Complex *tables,float *work,float dry_gain,float wet_gain){
    if(!input||!output||!spectra||!ring||!partitions||partitions>4096||!position||*position>=partitions||!tables||!work)return 0;
    float *padded=work,*time=work+256;
    Complex *frequency=(Complex*)(work+512),*temporary=(Complex*)(work+770);
    for(U i=0;i<128;i++){padded[i]=input[i];padded[i+128]=0;}
    ft_cab_forward(padded,frequency,temporary,tables,tables+256);
    for(U j=0;j<partitions;j++){
        U slot=(*position+j)%partitions;
        for(U k=0;k<128;k++){
            Complex product=mul(frequency[k],spectra[j*129+k]);
            ring[slot*129+k]=add(ring[slot*129+k],product);
        }
    }
    Complex *current=ring+*position*129;
    current[128].r=current[128].i=0;
    ft_cab_inverse(current,time,temporary,tables+128,tables+384);
    for(U i=0;i<128;i++){
        float wet=time[i+128]*(1.f/256.f);
        float a=input[i]*dry_gain,b=wet*wet_gain;
        output[i]=a+b;
    }
    for(U k=0;k<129;k++)current[k].r=current[k].i=0;
    *position=(*position+1)%partitions;
    return 1;
}
