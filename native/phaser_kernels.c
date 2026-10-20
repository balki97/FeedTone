/* Independent reconstruction of the current 0x61033 filter/phaser models. */
typedef unsigned int U;
typedef long double E;
#include "portable.h"
#define EXPORT FT_EXPORT
int _fltused=0;
/* Sine/cosine at multiples of pi/32, generated from 110-digit arithmetic.
   Columns: cos(angle)-nearest_power_of_two, sin_hi, sin_lo, power_of_two.
   The table contains mathematical constants, not captured tone outputs. */
static const double trig_table[64][4]={
 {0x0.0p+0, 0x0.0p+0, 0x0.0p+0, 0x1.0000000000000p+0},
 {-0x1.3b92e176d6d31p-8, 0x1.917a6bc29b42cp-4, -0x1.e2718d26ed688p-60, 0x1.0000000000000p+0},
 {-0x1.3ad06011469fbp-6, 0x1.8f8b83c69a60bp-3, -0x1.26d19b9ff8d82p-57, 0x1.0000000000000p+0},
 {-0x1.60bea939d225ap-5, 0x1.294062ed59f06p-2, -0x1.5d28da2c4612dp-56, 0x1.0000000000000p+0},
 {-0x1.37ca1866b95cfp-4, 0x1.87de2a6aea963p-2, -0x1.72cedd3d5a610p-57, 0x1.0000000000000p+0},
 {-0x1.e3a6873fa1279p-4, 0x1.e2b5d3806f63bp-2, 0x1.e0d891d3c6841p-58, 0x1.0000000000000p+0},
 {-0x1.592675bc57974p-3, 0x1.1c73b39ae68c8p-1, 0x1.b25dd267f6600p-55, 0x1.0000000000000p+0},
 {-0x1.d0dfe53aba2fdp-3, 0x1.44cf325091dd6p-1, 0x1.8076a2cfdc6b3p-57, 0x1.0000000000000p+0},
 {0x1.a827999fcef32p-3, 0x1.6a09e667f3bcdp-1, -0x1.bdd3413b26456p-55, 0x1.0000000000000p-1},
 {0x1.133cc94247758p-3, 0x1.8bc806b151741p-1, -0x1.2c5e12ed1336dp-55, 0x1.0000000000000p-1},
 {0x1.c73b39ae68c87p-5, 0x1.a9b66290ea1a3p-1, 0x1.9f630e8b6dac8p-60, 0x1.0000000000000p-1},
 {-0x1.d4a2c7f909c4ep-6, 0x1.c38b2f180bdb1p-1, -0x1.6e0b1757c8d07p-56, 0x1.0000000000000p-1},
 {-0x1.e087565455a75p-4, 0x1.d906bcf328d46p-1, 0x1.457e610231ac2p-56, 0x1.0000000000000p-1},
 {0x1.4a03176acf82dp-5, 0x1.e9f4156c62ddap-1, 0x1.760b1e2e3f81ep-55, 0x1.0000000000000p-2},
 {-0x1.c1d1f0e5967d5p-5, 0x1.f6297cff75cb0p-1, 0x1.562172a361fd3p-56, 0x1.0000000000000p-2},
 {-0x1.ba1650f592f50p-6, 0x1.fd88da3d12526p-1, -0x1.87df6378811c7p-55, 0x1.0000000000000p-3},
 {0x0.0p+0, 0x1.0000000000000p+0, 0x0.0p+0, 0x0.0p+0},
 {0x1.ba1650f592f50p-6, 0x1.fd88da3d12526p-1, -0x1.87df6378811c7p-55, -0x1.0000000000000p-3},
 {0x1.c1d1f0e5967d5p-5, 0x1.f6297cff75cb0p-1, 0x1.562172a361fd3p-56, -0x1.0000000000000p-2},
 {-0x1.4a03176acf82dp-5, 0x1.e9f4156c62ddap-1, 0x1.760b1e2e3f81ep-55, -0x1.0000000000000p-2},
 {0x1.e087565455a75p-4, 0x1.d906bcf328d46p-1, 0x1.457e610231ac2p-56, -0x1.0000000000000p-1},
 {0x1.d4a2c7f909c4ep-6, 0x1.c38b2f180bdb1p-1, -0x1.6e0b1757c8d07p-56, -0x1.0000000000000p-1},
 {-0x1.c73b39ae68c87p-5, 0x1.a9b66290ea1a3p-1, 0x1.9f630e8b6dac8p-60, -0x1.0000000000000p-1},
 {-0x1.133cc94247758p-3, 0x1.8bc806b151741p-1, -0x1.2c5e12ed1336dp-55, -0x1.0000000000000p-1},
 {-0x1.a827999fcef32p-3, 0x1.6a09e667f3bcdp-1, -0x1.bdd3413b26456p-55, -0x1.0000000000000p-1},
 {0x1.d0dfe53aba2fdp-3, 0x1.44cf325091dd6p-1, 0x1.8076a2cfdc6b3p-57, -0x1.0000000000000p+0},
 {0x1.592675bc57974p-3, 0x1.1c73b39ae68c8p-1, 0x1.b25dd267f6600p-55, -0x1.0000000000000p+0},
 {0x1.e3a6873fa1279p-4, 0x1.e2b5d3806f63bp-2, 0x1.e0d891d3c6841p-58, -0x1.0000000000000p+0},
 {0x1.37ca1866b95cfp-4, 0x1.87de2a6aea963p-2, -0x1.72cedd3d5a610p-57, -0x1.0000000000000p+0},
 {0x1.60bea939d225ap-5, 0x1.294062ed59f06p-2, -0x1.5d28da2c4612dp-56, -0x1.0000000000000p+0},
 {0x1.3ad06011469fbp-6, 0x1.8f8b83c69a60bp-3, -0x1.26d19b9ff8d82p-57, -0x1.0000000000000p+0},
 {0x1.3b92e176d6d31p-8, 0x1.917a6bc29b42cp-4, -0x1.e2718d26ed688p-60, -0x1.0000000000000p+0},
 {0x0.0p+0, 0x0.0p+0, 0x0.0p+0, -0x1.0000000000000p+0},
 {0x1.3b92e176d6d31p-8, -0x1.917a6bc29b42cp-4, 0x1.e2718d26ed688p-60, -0x1.0000000000000p+0},
 {0x1.3ad06011469fbp-6, -0x1.8f8b83c69a60bp-3, 0x1.26d19b9ff8d82p-57, -0x1.0000000000000p+0},
 {0x1.60bea939d225ap-5, -0x1.294062ed59f06p-2, 0x1.5d28da2c4612dp-56, -0x1.0000000000000p+0},
 {0x1.37ca1866b95cfp-4, -0x1.87de2a6aea963p-2, 0x1.72cedd3d5a610p-57, -0x1.0000000000000p+0},
 {0x1.e3a6873fa1279p-4, -0x1.e2b5d3806f63bp-2, -0x1.e0d891d3c6841p-58, -0x1.0000000000000p+0},
 {0x1.592675bc57974p-3, -0x1.1c73b39ae68c8p-1, -0x1.b25dd267f6600p-55, -0x1.0000000000000p+0},
 {0x1.d0dfe53aba2fdp-3, -0x1.44cf325091dd6p-1, -0x1.8076a2cfdc6b3p-57, -0x1.0000000000000p+0},
 {-0x1.a827999fcef32p-3, -0x1.6a09e667f3bcdp-1, 0x1.bdd3413b26456p-55, -0x1.0000000000000p-1},
 {-0x1.133cc94247758p-3, -0x1.8bc806b151741p-1, 0x1.2c5e12ed1336dp-55, -0x1.0000000000000p-1},
 {-0x1.c73b39ae68c87p-5, -0x1.a9b66290ea1a3p-1, -0x1.9f630e8b6dac8p-60, -0x1.0000000000000p-1},
 {0x1.d4a2c7f909c4ep-6, -0x1.c38b2f180bdb1p-1, 0x1.6e0b1757c8d07p-56, -0x1.0000000000000p-1},
 {0x1.e087565455a75p-4, -0x1.d906bcf328d46p-1, -0x1.457e610231ac2p-56, -0x1.0000000000000p-1},
 {-0x1.4a03176acf82dp-5, -0x1.e9f4156c62ddap-1, -0x1.760b1e2e3f81ep-55, -0x1.0000000000000p-2},
 {0x1.c1d1f0e5967d5p-5, -0x1.f6297cff75cb0p-1, -0x1.562172a361fd3p-56, -0x1.0000000000000p-2},
 {0x1.ba1650f592f50p-6, -0x1.fd88da3d12526p-1, 0x1.87df6378811c7p-55, -0x1.0000000000000p-3},
 {0x0.0p+0, -0x1.0000000000000p+0, 0x0.0p+0, 0x0.0p+0},
 {-0x1.ba1650f592f50p-6, -0x1.fd88da3d12526p-1, 0x1.87df6378811c7p-55, 0x1.0000000000000p-3},
 {-0x1.c1d1f0e5967d5p-5, -0x1.f6297cff75cb0p-1, -0x1.562172a361fd3p-56, 0x1.0000000000000p-2},
 {0x1.4a03176acf82dp-5, -0x1.e9f4156c62ddap-1, -0x1.760b1e2e3f81ep-55, 0x1.0000000000000p-2},
 {-0x1.e087565455a75p-4, -0x1.d906bcf328d46p-1, -0x1.457e610231ac2p-56, 0x1.0000000000000p-1},
 {-0x1.d4a2c7f909c4ep-6, -0x1.c38b2f180bdb1p-1, 0x1.6e0b1757c8d07p-56, 0x1.0000000000000p-1},
 {0x1.c73b39ae68c87p-5, -0x1.a9b66290ea1a3p-1, -0x1.9f630e8b6dac8p-60, 0x1.0000000000000p-1},
 {0x1.133cc94247758p-3, -0x1.8bc806b151741p-1, 0x1.2c5e12ed1336dp-55, 0x1.0000000000000p-1},
 {0x1.a827999fcef32p-3, -0x1.6a09e667f3bcdp-1, 0x1.bdd3413b26456p-55, 0x1.0000000000000p-1},
 {-0x1.d0dfe53aba2fdp-3, -0x1.44cf325091dd6p-1, -0x1.8076a2cfdc6b3p-57, 0x1.0000000000000p+0},
 {-0x1.592675bc57974p-3, -0x1.1c73b39ae68c8p-1, -0x1.b25dd267f6600p-55, 0x1.0000000000000p+0},
 {-0x1.e3a6873fa1279p-4, -0x1.e2b5d3806f63bp-2, -0x1.e0d891d3c6841p-58, 0x1.0000000000000p+0},
 {-0x1.37ca1866b95cfp-4, -0x1.87de2a6aea963p-2, 0x1.72cedd3d5a610p-57, 0x1.0000000000000p+0},
 {-0x1.60bea939d225ap-5, -0x1.294062ed59f06p-2, 0x1.5d28da2c4612dp-56, 0x1.0000000000000p+0},
 {-0x1.3ad06011469fbp-6, -0x1.8f8b83c69a60bp-3, 0x1.26d19b9ff8d82p-57, 0x1.0000000000000p+0},
 {-0x1.3b92e176d6d31p-8, -0x1.917a6bc29b42cp-4, 0x1.e2718d26ed688p-60, 0x1.0000000000000p+0},
};
/* Recovered compensated SSE2 polynomial for the phaser's bounded angles.
   All arithmetic here intentionally rounds to double; x87 FSIN differs at
   a few ULP boundaries and its error persists in quiet feedback tails. */
static double legacy_trig(double x,U quarter_turn){
 if(x==0)return quarter_turn?1:x;
 double scaled=x*10.185916357881302;
 #if defined(__x86_64__) || defined(_M_X64)
int segment;__asm__("cvtsd2si %1,%0":"=r"(segment):"x"(scaled));
#else
 int segment=(int)nearbyint(scaled);
#endif
 double n=(scaled+6755399441055744.0)-6755399441055744.0;
 double initial=x-n*0.09817477042088285;
 double middle=n*3.798187816439979e-12;
 double r=initial-middle;
 double correction=n*1.2639164054974691e-22-((initial-r)-middle);
 const double*t=trig_table[((U)segment+quarter_turn)&63];
 double co=t[0]+t[3];
 correction*=r*t[1]-co;
 double square=r*r,fourth=square*square;
 double sp=(-1.0/6+square*(1.0/120))+fourth*((-1.0/5040)+(1.0/362880*initial)*r);
 double cp=(-1.0/2+square*(1.0/24))+fourth*((-1.0/720)+(1.0/40320*initial)*r);
 double first=t[3]*r,second=t[0]*r;
 double linear=first+t[1],leading=second+linear;
 correction+=t[2];
 correction+=(t[1]-linear)+first;
 correction+=(linear-leading)+second;
 correction+=sp*((co*r)*square);
 correction+=cp*(t[1]*square);
 return leading+correction;
}
static E sine(E x){return (E)legacy_trig((double)x,0);}
static E cosine(E x){return (E)legacy_trig((double)x,16);}
#if defined(__x86_64__) || defined(_M_X64)
static E power(E b,E e){
 E v,i,r;__asm__("fyl2x":"=t"(v):"0"(b),"u"(e):"st(1)");
 __asm__("frndint":"=t"(i):"0"(v));v-=i;
 __asm__("f2xm1":"=t"(r):"0"(v));r+=1;
 __asm__("fscale":"=t"(r):"0"(r),"u"(i));return r;
}
#else
static E power(E b,E e){return powl(b,e);}
#endif
typedef struct { U model,mode,wave,count;float p[9];double c[5],s[3];} Stage;
typedef struct {Stage bands[3];} Phaser;
/* Base-ten specialization of the compensated log/exp algorithm.
   Constants are generated mathematically by tools/generate_phaser_table.py.
   Low residuals and polynomial constants use the recovered toward-zero rule. */
static const double exp2_table[128][2]={
 {0x1.0000000000000p+0, 0x0.0p+0},
 {0x1.0163da9fb3335p+0, 0x1.b61299ab8cdb7p-54},
 {0x1.02c9a3e778061p+0, -0x1.19083535b085dp-56},
 {0x1.04315e86e7f85p+0, -0x1.0a31c1977c96ep-54},
 {0x1.059b0d3158574p+0, 0x1.d73e2a475b465p-55},
 {0x1.0706b29ddf6dep+0, -0x1.c91dfe2b13c26p-55},
 {0x1.0874518759bc8p+0, 0x1.186be4bb284ffp-57},
 {0x1.09e3ecac6f383p+0, 0x1.1487818316135p-54},
 {0x1.0b5586cf9890fp+0, 0x1.8a62e4adc610ap-54},
 {0x1.0cc922b7247f7p+0, 0x1.01edc16e24f71p-54},
 {0x1.0e3ec32d3d1a2p+0, 0x1.03a1727c57b52p-59},
 {0x1.0fb66affed31bp+0, -0x1.b9bedc44ebd7bp-57},
 {0x1.11301d0125b51p+0, -0x1.6c51039449b39p-54},
 {0x1.12abdc06c31ccp+0, -0x1.1b514b36ca5c7p-58},
 {0x1.1429aaea92de0p+0, -0x1.32fbf9af1369ep-54},
 {0x1.15a98c8a58e51p+0, 0x1.2406ab9eeab09p-55},
 {0x1.172b83c7d517bp+0, -0x1.19041b9d78a75p-55},
 {0x1.18af9388c8deap+0, -0x1.11023d1970f6bp-54},
 {0x1.1a35beb6fcb75p+0, 0x1.e5b4c7b4968e4p-55},
 {0x1.1bbe084045cd4p+0, -0x1.95386352ef607p-54},
 {0x1.1d4873168b9aap+0, 0x1.e016e00a2643cp-54},
 {0x1.1ed5022fcd91dp+0, -0x1.1df98027bb78bp-54},
 {0x1.2063b88628cd6p+0, 0x1.dc775814a8494p-55},
 {0x1.21f49917ddc96p+0, 0x1.2a97e9494a5edp-55},
 {0x1.2387a6e756238p+0, 0x1.9b07eb6c70572p-54},
 {0x1.251ce4fb2a63fp+0, 0x1.ac155bef4f4a4p-55},
 {0x1.26b4565e27cddp+0, 0x1.2bd339940e9d9p-55},
 {0x1.284dfe1f56381p+0, -0x1.a4c3a8c3f0d7dp-54},
 {0x1.29e9df51fdee1p+0, 0x1.612e8afad1255p-55},
 {0x1.2b87fd0dad990p+0, -0x1.10adcd6381aa3p-59},
 {0x1.2d285a6e4030bp+0, 0x1.0024754db41d4p-54},
 {0x1.2ecafa93e2f56p+0, 0x1.1ca0f45d52383p-56},
 {0x1.306fe0a31b715p+0, 0x1.6f46ad23182e4p-55},
 {0x1.32170fc4cd831p+0, 0x1.a9ce78e18047cp-55},
 {0x1.33c08b26416ffp+0, 0x1.32721843659a5p-54},
 {0x1.356c55f929ff1p+0, -0x1.b5cee5c4e4628p-55},
 {0x1.371a7373aa9cbp+0, -0x1.63aeabf42eae1p-54},
 {0x1.38cae6d05d866p+0, -0x1.e958d3c9904bcp-54},
 {0x1.3a7db34e59ff7p+0, -0x1.5e436d661f5e2p-56},
 {0x1.3c32dc313a8e5p+0, -0x1.efff8375d29c3p-54},
 {0x1.3dea64c123422p+0, 0x1.ada0911f09ebbp-55},
 {0x1.3fa4504ac801cp+0, -0x1.7d023f956f9f3p-54},
 {0x1.4160a21f72e2ap+0, -0x1.ef3691c309278p-58},
 {0x1.431f5d950a897p+0, -0x1.1c7dde35f7998p-55},
 {0x1.44e086061892dp+0, 0x1.89b7a04ef80cfp-59},
 {0x1.46a41ed1d0057p+0, 0x1.c944bd1648a76p-54},
 {0x1.486a2b5c13cd0p+0, 0x1.3c1a3b69062f0p-56},
 {0x1.4a32af0d7d3dep+0, 0x1.9cb62f3d1be56p-54},
 {0x1.4bfdad5362a27p+0, 0x1.d4397afec42e2p-56},
 {0x1.4dcb299fddd0dp+0, 0x1.8ecdbbc6a7833p-54},
 {0x1.4f9b2769d2ca7p+0, -0x1.4b309d25957e3p-54},
 {0x1.516daa2cf6642p+0, -0x1.f768569bd93eep-55},
 {0x1.5342b569d4f82p+0, -0x1.07abe1db13cacp-55},
 {0x1.551a4ca5d920fp+0, -0x1.d689cefede59ap-55},
 {0x1.56f4736b527dap+0, 0x1.9bb2c011d93acp-54},
 {0x1.58d12d497c7fdp+0, 0x1.295e15b9a1de7p-55},
 {0x1.5ab07dd485429p+0, 0x1.6324c054647acp-54},
 {0x1.5c9268a5946b7p+0, 0x1.c4b1b816986a2p-60},
 {0x1.5e76f15ad2148p+0, 0x1.ba6f93080e65dp-54},
 {0x1.605e1b976dc09p+0, -0x1.3e2429b56de47p-54},
 {0x1.6247eb03a5585p+0, -0x1.383c17e40b496p-54},
 {0x1.6434634ccc320p+0, -0x1.c483c759d8932p-55},
 {0x1.6623882552225p+0, -0x1.bb60987591c33p-54},
 {0x1.68155d44ca973p+0, 0x1.038ae44f73e64p-57},
 {0x1.6a09e667f3bcdp+0, -0x1.bdd3413b26455p-54},
 {0x1.6c012750bdabfp+0, -0x1.2895667ff0b0cp-56},
 {0x1.6dfb23c651a2fp+0, -0x1.bbe3a683c88aap-57},
 {0x1.6ff7df9519484p+0, -0x1.83c0f25860ef6p-55},
 {0x1.71f75e8ec5f74p+0, -0x1.16e4786887a99p-55},
 {0x1.73f9a48a58174p+0, -0x1.0a8d96c65d53bp-54},
 {0x1.75feb564267c9p+0, -0x1.0245957316dd3p-54},
 {0x1.780694fde5d3fp+0, 0x1.866b80a02162cp-54},
 {0x1.7a11473eb0187p+0, -0x1.41577ee04992fp-55},
 {0x1.7c1ed0130c132p+0, 0x1.f124cd1164dd5p-54},
 {0x1.7e2f336cf4e62p+0, 0x1.05d02ba15797ep-56},
 {0x1.80427543e1a12p+0, -0x1.27c86626d972ap-54},
 {0x1.82589994cce13p+0, -0x1.d4c1dd41532d7p-54},
 {0x1.8471a4623c7adp+0, -0x1.8d684a341cdfbp-55},
 {0x1.868d99b4492edp+0, -0x1.fc6f89bd4f6bap-54},
 {0x1.88ac7d98a6699p+0, 0x1.994c2f37cb53ap-54},
 {0x1.8ace5422aa0dbp+0, 0x1.6e9f156864b26p-54},
 {0x1.8cf3216b5448cp+0, -0x1.0d55e32e9e3aap-56},
 {0x1.8f1ae99157736p+0, 0x1.5cc13a2e3976cp-55},
 {0x1.9145b0b91ffc6p+0, -0x1.dd6792e582523p-54},
 {0x1.93737b0cdc5e5p+0, -0x1.75fc781b57ebbp-57},
 {0x1.95a44cbc8520fp+0, -0x1.64b7c96a5f039p-56},
 {0x1.97d829fde4e50p+0, -0x1.d185b7c1b85d0p-54},
 {0x1.9a0f170ca07bap+0, -0x1.173bd91cee632p-54},
 {0x1.9c49182a3f090p+0, 0x1.c7c46b071f2bep-56},
 {0x1.9e86319e32323p+0, 0x1.824ca78e64c6ep-56},
 {0x1.a0c667b5de565p+0, -0x1.359495d1cd532p-54},
 {0x1.a309bec4a2d33p+0, 0x1.6305c7ddc36abp-54},
 {0x1.a5503b23e255dp+0, -0x1.d2f6edb8d41e1p-54},
 {0x1.a799e1330b358p+0, 0x1.bcb7ecac563c6p-54},
 {0x1.a9e6b5579fdbfp+0, 0x1.0fac90ef7fd31p-54},
 {0x1.ac36bbfd3f37ap+0, -0x1.f9234cae76cd0p-55},
 {0x1.ae89f995ad3adp+0, 0x1.7a1cd345dcc81p-54},
 {0x1.b0e07298db666p+0, -0x1.bdef54c80e424p-54},
 {0x1.b33a2b84f15fbp+0, -0x1.2805e3084d707p-57},
 {0x1.b59728de5593ap+0, -0x1.c71dfbbba6de3p-54},
 {0x1.b7f76f2fb5e47p+0, -0x1.5584f7e54ac3ap-56},
 {0x1.ba5b030a1064ap+0, -0x1.efcd30e54292ep-54},
 {0x1.bcc1e904bc1d2p+0, 0x1.23dd07a2d9e84p-55},
 {0x1.bf2c25bd71e09p+0, -0x1.efdca3f6b9c72p-54},
 {0x1.c199bdd85529cp+0, 0x1.11065895048ddp-55},
 {0x1.c40ab5fffd07ap+0, 0x1.b4537e083c60ap-54},
 {0x1.c67f12e57d14bp+0, 0x1.2884dff483cacp-54},
 {0x1.c8f6d9406e7b5p+0, 0x1.1acbc48805c44p-56},
 {0x1.cb720dcef9069p+0, 0x1.503cbd1e949dbp-56},
 {0x1.cdf0b555dc3fap+0, -0x1.dd83b53829d72p-55},
 {0x1.d072d4a07897cp+0, -0x1.cbc3743797a9cp-54},
 {0x1.d2f87080d89f2p+0, -0x1.d487b719d8577p-54},
 {0x1.d5818dcfba487p+0, 0x1.2ed02d75b3706p-55},
 {0x1.d80e316c98398p+0, -0x1.11ec18beddfe8p-54},
 {0x1.da9e603db3285p+0, 0x1.c2300696db532p-54},
 {0x1.dd321f301b460p+0, 0x1.2da5778f018c2p-54},
 {0x1.dfc97337b9b5fp+0, -0x1.1a5cd4f184b5bp-54},
 {0x1.e264614f5a129p+0, -0x1.7b627817a1496p-54},
 {0x1.e502ee78b3ff6p+0, 0x1.39e8980a9cc8fp-55},
 {0x1.e7a51fbc74c83p+0, 0x1.2d522ca0c8de1p-54},
 {0x1.ea4afa2a490dap+0, -0x1.e9c23179c2893p-54},
 {0x1.ecf482d8e67f1p+0, -0x1.c93f3b411ad8cp-54},
 {0x1.efa1bee615a27p+0, 0x1.dc7f486a4b6b0p-54},
 {0x1.f252b376bba97p+0, 0x1.3a1a5bf0d8e43p-54},
 {0x1.f50765b6e4540p+0, 0x1.9d3e12dd8a18ap-54},
 {0x1.f7bfdad9cbe14p+0, -0x1.dbb12d0063509p-54},
 {0x1.fa7c1819e90d8p+0, 0x1.74853f3a5931ep-55},
 {0x1.fd3c22b8f71f1p+0, 0x1.2eb74966579e7p-57},
};
typedef unsigned long long QWord;
static double split_high(double x){union{double f;QWord u;}v={x};v.u&=0xfffffffff8000000ULL;return v.f;}
static double legacy_power10(double y){
 if(y==0)return 1;
 const double log_high=0x1.a934f0979a400p+1,log_low=-0x1.e1e7e61c4ec88p-45,residual=-0x1.55e4000000000p-24;
 double yh=split_high(y),yl=y-yh,lh=split_high(log_high),ll=log_high-lh;
 double scaled=(yh*lh)*128;
 #if defined(__x86_64__) || defined(_M_X64)
int n;__asm__("cvtsd2si %1,%0":"=r"(n):"x"(scaled));
#else
 int n=(int)nearbyint(scaled);
#endif
 double rounded=(scaled+6755399441055744.0)-6755399441055744.0;
 double remainder=(scaled-rounded)*0.0078125;
 double low=yh*ll+lh*yl;low+=ll*yl;
 double square=residual*residual;
 double p0=0x1.47fd462b3b816p-3*residual+-0x1.550472a8bb463p-4*square;
 double p1=0x1.9c3a6966457eep-24*residual+-0x1.62e4346694107p-2*square;
 double correction=p0*square+p1;
 correction+=log_low;correction*=y;
 low+=correction;remainder+=low;
 union{double f;QWord u;}scale;scale.u=(QWord)((n>>7)+1023)<<52;
 const double*t=exp2_table[(U)n&127];double high=t[0]*scale.f,tail=t[1]*scale.f;
 double r2=remainder*remainder;
 double a=(0x1.3b2ab6fba4e77p-7+0x1.5d87fe78a6731p-10*remainder)*r2;
 double b=(0x1.ebfbdff82c58ep-3+0x1.c6b08d704a0bfp-5*remainder)*r2;
 double result=(r2*high)*a;
 result+=tail;result+=b*high;result+=(0x1.62e42fefa39efp-1*remainder)*high;result+=high;
 return result;
}
static void configure(Stage *s,float frequency,float gain,float q,float shape){
 if(s->model==6){
  double amplitude=legacy_power10((double)((E)gain/40));
  double angle=(double)((E)frequency*(E)(double)6.28318530717959/48000);
  double co=(double)cosine((E)angle);
  E alpha=(E)(double)sine((E)angle)/((E)q+(E)q),a=alpha*(E)amplitude;
  double b0=(double)(a+1),b1=(double)((E)co*-2),b2=(double)(1-a);
  alpha/=(E)amplitude;
  double a0=(double)(alpha+1),a1=b1,a2=(double)(1-alpha);
  s->c[0]=(double)((E)b0/a0);s->c[1]=(double)((E)b1/a0);s->c[2]=(double)((E)b2/a0);
  s->c[3]=(double)((E)a1/a0);s->c[4]=(double)((E)a2/a0);
 }else if(s->model==21){
  float fraction=(float)((E)frequency/48000);
  if(fraction<0)fraction=0;if(fraction>.5f)fraction=.5f;
  float damp=(float)((E)shape*(E)(double)0.7999999970197678+(E)(double)0.20000000298023224);
  double half=(double)((E)fraction*.5L);if(half>.25)half=.25;
  E f=(E)(double)sine((E)half*(E)(double)3.141592653589793)*2;
  s->c[0]=(double)f;
  double bound=(double)(2/f-f*.5L);
  E d=(1-(E)(double)power((E)damp,.25L))*2;
  double value=bound<=2?bound:2;
  s->c[1]=value<=d?value:(double)d;
 }
}
static void run(Stage *s,float *a,U frames){
 if(s->model==0)return;
 if(s->model==6){
  for(U i=0;i<frames;i++){
   float input=a[i];
   if(input>-(float)1e-10f&&input<(float)1e-10f)input=0;
   E y=(E)s->c[0]*input+s->s[0];
   s->s[0]=(double)(((E)s->c[1]*input+s->s[1])-(E)s->c[3]*y);
   E tail=((E)s->c[2]*input-(E)s->c[4]*y)+(E)(float)1e-10f;
   s->s[1]=tail>-(E)(float)1e-10f&&tail<(E)(float)1e-10f?0:(double)tail;
   double output=(double)y;
   a[i]=output>-(double)(float)1e-10f&&output<(double)(float)1e-10f?0:(float)output;
  }
 }else if(s->model==21){
  for(U i=0;i<frames;i++){
   E low=(E)s->s[2]*s->c[0]+s->s[0];s->s[0]=(double)low;
   E high=((E)a[i]-(E)s->s[2]*s->c[1])-low;s->s[1]=(double)high;
   E band=(high*s->c[0]+s->s[2])-((E)s->s[2]*(E)(double)0.05000000074505806*s->s[2]*s->s[2]);
   s->s[2]=(double)band;
   E first=((E)s->s[0]-s->s[1])*.5L;
   low=(E)s->s[2]*s->c[0]+s->s[0];s->s[0]=(double)low;
   high=((E)a[i]-band*s->c[1])-low;s->s[1]=(double)high;
   s->s[2]=(double)((high*s->c[0]+s->s[2])-((E)s->s[2]*(E)(double)0.05000000074505806*s->s[2]*s->s[2]));
   a[i]=(float)(((E)s->s[0]-s->s[1])*.5L+first);
  }
 }
}
EXPORT U ft_phaser_abi(void){return 3;}
EXPORT U ft_phaser_state_size(void){return sizeof(Phaser);}
EXPORT int ft_phaser_initialize(Phaser *p){
 if(!p)return 0;unsigned char *b=(unsigned char*)p;for(U i=0;i<sizeof(Phaser);i++)b[i]=0;return 1;
}
EXPORT int ft_phaser_parameter(Phaser *p,U id,float v){
 if(!p||id>=36)return 0;Stage *s=p->bands+id/12;U k=id%12;
 if(k==0){U model=(U)v;if(model!=0&&model!=6&&model!=21)return 0;if(s->model!=model){for(U i=0;i<3;i++)s->s[i]=0;s->model=model;}}
 else if(k==5)s->mode=(U)v;
 else if(k==6)s->wave=(U)v;
 else {U at=k<=4?k-1:k-3;s->p[at]=v;}
 configure(s,s->p[0],s->p[3],s->p[1],s->p[2]);return 1;
}
EXPORT int ft_phaser_reset(Phaser *p){if(!p)return 0;for(U j=0;j<3;j++)for(U i=0;i<3;i++)p->bands[j].s[i]=0;return 1;}
EXPORT int ft_phaser_process(Phaser *p,float *a,U frames){
 if(!p||!a||frames!=128)return 0;
 for(U j=0;j<3;j++){
  Stage *s=p->bands+j;
  if(s->mode==0){run(s,a,frames);continue;}
  if(s->mode!=1)return 0;
  U period=(U)(long long)((E)s->p[4]*(E)(double).001*48000+.5L);if(!period)continue;
  for(U at=0;at<frames;at+=50){
   U n=frames-at;if(n>50)n=50;
   float phase=(float)((E)s->count/(E)period),wave;
   if(s->wave==0){float angle=(float)((E)phase*2*(E)(double)3.1415927410125732);float sn=(float)sine((E)angle);wave=(float)(((E)sn+1)*.5L);}
   else if(s->wave==1)wave=phase<.5f?0:1;
   else if(s->wave==2)wave=phase;
   else if(s->wave==3)wave=(float)(1-(E)phase);
   else if(s->wave==4)wave=(float)(phase<.5f?(E)phase*2:1-((E)phase-.5L)*2);
   else continue;
   float freq=(float)((E)s->p[0]+((E)s->p[5]-s->p[0])*(E)wave);
   float gain=(float)((E)s->p[3]+(E)wave*((E)s->p[6]-s->p[3]));
   float q=(float)((E)s->p[1]+(E)wave*((E)s->p[7]-s->p[1]));
   float shape=(float)((E)s->p[2]+(E)wave*((E)s->p[8]-s->p[2]));
   configure(s,freq,gain,q,shape);run(s,a+at,n);s->count=(s->count+n)%period;
  }
 }
 return 1;
}


