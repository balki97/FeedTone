/* Independent mixed-radix real FFT and extended-precision sqrt-Hann window. */
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
#if defined(__x86_64__) || defined(_M_X64)
static long double sqrt80(long double x){long double y;__asm__("fsqrt":"=t"(y):"0"(x));return y;}
#else
static long double sqrt80(long double x){return sqrtl(x);}
#endif
static Complex add(Complex a,Complex b){Complex c={a.r+b.r,a.i+b.i};return c;}
static Complex sub(Complex a,Complex b){Complex c={a.r-b.r,a.i-b.i};return c;}
static Complex mul(Complex a,Complex b){float rr=a.r*b.r,ii=a.i*b.i,ri=a.r*b.i,ir=a.i*b.r;Complex c={rr-ii,ir+ri};return c;}
static Complex conj(Complex a){a.i=-a.i;return a;}
static U radix(U n){if(n%4==0)return 4;if(n%2==0)return 2;for(U p=3;p*p<=n;p+=2)if(n%p==0)return p;return n;}
static int valid(U n){if(n<4||n>16384||n%4)return 0;for(U left=n/2;left>1;){U p=radix(left);if(p>31)return 0;left/=p;}return 1;}
static void leaf16(Complex *out,const Complex *input,U stride,const Complex *twiddle,U inverse){
    Complex group[16];float sign=inverse?1.f:-1.f;
    for(U j=0;j<4;j++){
        Complex a=input[j*stride],b=input[(j+4)*stride],c=input[(j+8)*stride],d=input[(j+12)*stride];
        Complex zero={((c.r+a.r)+b.r)+d.r,((c.i+a.i)+b.i)+d.i};
        Complex two={((c.r+a.r)-b.r)-d.r,((c.i+a.i)-b.i)-d.i};
        Complex one={((-sign*b.i+a.r)-c.r)+sign*d.i,((sign*b.r+a.i)-c.i)-sign*d.r};
        Complex three={((sign*b.i+a.r)-c.r)-sign*d.i,((-sign*b.r+a.i)-c.i)+sign*d.r};
        group[j*4]=zero;group[j*4+1]=one;group[j*4+2]=two;group[j*4+3]=three;
    }
    for(U k=0;k<4;k++){
        Complex s0=group[k],s1=mul(group[k+4],twiddle[k*stride]),s2=mul(group[k+8],twiddle[2*k*stride]),s3=mul(group[k+12],twiddle[3*k*stride]);
        Complex a=add(s0,s2),b=sub(s0,s2),c=add(s3,s1),d=sub(s1,s3);
        out[k]=add(a,c);out[k+8]=sub(a,c);
        Complex one={b.r-sign*d.i,b.i+sign*d.r},three={b.r+sign*d.i,b.i-sign*d.r};out[k+4]=one;out[k+12]=three;
    }
}
API int ft_pitch_fft_tables(U n,Complex *forward,Complex *inverse,Complex *super_forward,Complex *super_inverse){
    if(!valid(n)||!forward||!inverse||!super_forward||!super_inverse)return 0;
    U size=n/2;const long double tau=(long double)(double)6.283185307179586,pi=(long double)(double)3.141592653589793;
    for(U k=0;k<size;k++){long double a=(long double)k*tau/(long double)size;
        forward[k].r=(float)cos80(-a);forward[k].i=(float)sin80(-a);inverse[k].r=(float)cos80(a);inverse[k].i=(float)sin80(a);}
    for(U k=0;k<size/2;k++){long double a=((long double)(k+1)/(long double)size+.5L)*pi;
        super_forward[k].r=(float)cos80(-a);super_forward[k].i=(float)sin80(-a);super_inverse[k].r=(float)cos80(a);super_inverse[k].i=(float)sin80(a);}
    return 1;
}
API int ft_pitch_window(U n,float *window,float *energy){
    if(!valid(n)||!window||!energy)return 0;
    long double angle=0,step=(long double)(double)6.283185307179586/(long double)(n-1),sum=0;
    for(U i=0;i<n/2;i++){long double h=(1.L-cos80(angle))*.5L;float value=(float)sqrt80(h);window[i]=window[n-1-i]=value;sum+=h;angle+=step;}
    *energy=(float)(sum*2.L);return 1;
}
static void fft(Complex *out,const Complex *input,U stride,U size,U total,const Complex *twiddle,U inverse){
    if(total==1024&&size==16&&stride==64){leaf16(out,input,stride,twiddle,inverse);return;}
    U p=radix(size),m=size/p;
    if(m==1){for(U j=0;j<p;j++)out[j]=input[j*stride];}
    else for(U j=0;j<p;j++)fft(out+j*m,input+j*stride,stride*p,m,total,twiddle,inverse);
    if(p==2){for(U k=0;k<m;k++){Complex a=out[k],b=mul(out[k+m],twiddle[k*stride]);out[k+m]=sub(a,b);out[k]=add(a,b);}return;}
    if(p==4&&m%2==0){for(U k=0;k<m;k++){
        Complex s0=out[k],s1=mul(out[k+m],twiddle[k*stride]),s2=mul(out[k+2*m],twiddle[2*k*stride]),s3=mul(out[k+3*m],twiddle[3*k*stride]);
        Complex a=add(s2,s0),b=sub(s0,s2),c=add(s3,s1),d=sub(s1,s3);out[k]=add(c,a);out[k+2*m]=sub(a,c);
        if(!inverse){Complex one={b.r+d.i,b.i-d.r},three={b.r-d.i,b.i+d.r};out[k+m]=one;out[k+3*m]=three;}
        else{Complex one={b.r-d.i,b.i+d.r},three={b.r+d.i,b.i-d.r};out[k+m]=one;out[k+3*m]=three;}}
        return;
    }
    if(p==3){float e=twiddle[stride*m].i;for(U k=0;k<m;k++){
        Complex s1=mul(out[k+m],twiddle[k*stride]),s2=mul(out[k+2*m],twiddle[2*k*stride]),sum=add(s2,s1);
        Complex base={out[k].r-sum.r*.5f,out[k].i-sum.i*.5f};float dr=e*(s1.r-s2.r),di=e*(s1.i-s2.i);
        out[k]=add(out[k],sum);Complex two={di+base.r,base.i-dr},one={base.r-di,dr+base.i};out[k+m]=one;out[k+2*m]=two;}return;
    }
    if(p==5){Complex ya=twiddle[stride*m],yb=twiddle[2*stride*m];for(U k=0;k<m;k++){
        Complex old=out[k],s1=mul(out[k+m],twiddle[k*stride]),s2=mul(out[k+2*m],twiddle[2*k*stride]),s3=mul(out[k+3*m],twiddle[3*k*stride]),s4=mul(out[k+4*m],twiddle[4*k*stride]);
        Complex a14=add(s4,s1),d14=sub(s1,s4),a23=add(s3,s2),d23=sub(s2,s3);
        out[k]=add(add(a23,a14),old);
        Complex a={(ya.r*a14.r+old.r)+yb.r*a23.r,(ya.r*a14.i+old.i)+yb.r*a23.i};
        Complex b={yb.i*d23.i+ya.i*d14.i,-(ya.i*d14.r)-yb.i*d23.r};out[k+m]=sub(a,b);out[k+4*m]=add(a,b);
        Complex c={(yb.r*a14.r+old.r)+ya.r*a23.r,(yb.r*a14.i+old.i)+ya.r*a23.i};
        Complex d={ya.i*d23.i-yb.i*d14.i,yb.i*d14.r-ya.i*d23.r};out[k+2*m]=add(c,d);out[k+3*m]=sub(c,d);
        }return;
    }
    for(U k=0;k<m;k++){Complex scratch[32];for(U j=0;j<p;j++)scratch[j]=out[k+j*m];
        for(U j=0;j<p;j++){Complex value=scratch[0];U step=stride*(k+j*m),index=0;
            for(U q=1;q<p;q++){index+=step;if(index>=total)index-=total;Complex s=scratch[q],w=twiddle[index];
                value.r+=s.r*w.r-s.i*w.i;value.i=value.i+(w.r*s.i+s.r*w.i);}
            out[k+j*m]=value;}}
}
API int ft_pitch_forward(U n,const float *input,Complex *output,Complex *temporary,const Complex *twiddle,const Complex *super){
    if(!valid(n)||!input||!output||!temporary||!twiddle||!super)return 0;U size=n/2;
    fft(temporary,(const Complex*)input,1,size,size,twiddle,0);
    for(U k=1;k<=size/2;k++){Complex fk=temporary[k],fn=conj(temporary[size-k]),even=add(fn,fk),odd=mul(sub(fk,fn),super[k-1]);
        Complex a=add(odd,even),b=conj(sub(even,odd));a.r*=.5f;a.i*=.5f;b.r*=.5f;b.i*=.5f;output[k]=a;output[size-k]=b;}
    output[0].r=temporary[0].i+temporary[0].r;output[0].i=0;output[size].r=temporary[0].r-temporary[0].i;output[size].i=0;return 1;
}
API int ft_pitch_inverse(U n,const Complex *input,float *output,Complex *temporary,const Complex *twiddle,const Complex *super){
    if(!valid(n)||!input||!output||!temporary||!twiddle||!super)return 0;U size=n/2;
    temporary[0].r=input[0].r+input[size].r;temporary[0].i=input[0].r-input[size].r;
    for(U k=1;k<=size/2;k++){Complex fk=input[k],fn=conj(input[size-k]),even=add(fn,fk),odd=mul(sub(fk,fn),super[k-1]);temporary[k]=add(odd,even);temporary[size-k]=conj(sub(even,odd));}
    fft((Complex*)output,temporary,1,size,size,twiddle,1);return 1;
}
