#ifdef _WIN32
/* Minimal Windows declarations for the freestanding bridge build. */
#include <stdint.h>
#define NULL ((void*)0)
typedef uint64_t size_t;
typedef uint32_t U;
typedef uint16_t W;
typedef void *Handle;
#define API __declspec(dllimport)
API Handle __stdcall VirtualAlloc(Handle,size_t,U,U);
API int __stdcall VirtualFree(Handle,size_t,U);
API U __stdcall GetModuleFileNameW(Handle,W*,U);
API Handle __stdcall CreateFileW(const W*,U,U,Handle,U,U,Handle);
API U __stdcall GetFileSize(Handle,U*);
API int __stdcall ReadFile(Handle,void*,U,U*,Handle);
API int __stdcall WriteFile(Handle,const void*,U,U*,Handle);
API int __stdcall CloseHandle(Handle);
API int __stdcall CreatePipe(Handle*,Handle*,void*,U);
API int __stdcall SetHandleInformation(Handle,U,U);
API int __stdcall PeekNamedPipe(Handle,void*,U,U*,U*,U*);
API uint64_t __stdcall GetTickCount64(void);
API void __stdcall Sleep(U);
API int __stdcall CreateProcessW(const W*,W*,Handle,Handle,int,U,Handle,const W*,void*,void*);
API U __stdcall WaitForSingleObject(Handle,U);
API int __stdcall TerminateProcess(Handle,U);
API U __stdcall GetTempPathW(U,W*);
API U __stdcall GetCurrentProcessId(void);
API int __stdcall InitializeProcThreadAttributeList(Handle,U,U,size_t*);
API int __stdcall UpdateProcThreadAttribute(Handle,U,size_t,Handle,size_t,Handle,size_t*);
API void __stdcall DeleteProcThreadAttributeList(Handle);
API Handle __stdcall CreateThread(Handle,size_t,U(__stdcall*)(void*),void*,U,U*);
API Handle __stdcall CreateEventW(Handle,int,int,const W*);
API int __stdcall SetEvent(Handle);
int _fltused;
static Handle module;
int __stdcall DllMain(Handle self,U reason,Handle reserved) {if(reason==1)module=self;return 1;}
static void *memcpy(void *dst,const void *src,size_t n) {unsigned char*d=dst;const unsigned char*s=src;for(size_t i=0;i<n;i++)d[i]=s[i];return dst;}
static void *memset(void *dst,int value,size_t n) {unsigned char*d=dst;for(size_t i=0;i<n;i++)d[i]=(unsigned char)value;return dst;}
static int memcmp(const void *one,const void *two,size_t n) {const unsigned char*a=one,*b=two;for(size_t i=0;i<n;i++)if(a[i]!=b[i])return a[i]-b[i];return 0;}
static char *strcpy(char*d,const char*s) {char*begin=d;while((*d++=*s++)){}return begin;}
static int strcmp(const char*a,const char*b) {while(*a&&*a==*b){a++;b++;}return(unsigned char)*a-(unsigned char)*b;}
static void *malloc(size_t n) {return VirtualAlloc(NULL,n?n:1,0x3000,4);}
static void free(void*p) {if(p)VirtualFree(p,0,0x8000);}
static int valid_normalized(double x) {return x>=0.0&&x<=1.0;}
static void widecopy(W*d,const W*s,U capacity) {U i=0;while(i+1<capacity&&s[i]){d[i]=s[i];i++;}d[i]=0;}
static void narrow(char*d,const W*s,U capacity) {U i=0;while(i+1<capacity&&s[i]){d[i]=s[i]<128?(char)s[i]:'?';i++;}d[i]=0;}
static void textwide(W*d,const char*s,U capacity) {U i=0;while(i+1<capacity&&s[i]){d[i]=(unsigned char)s[i];i++;}d[i]=0;}

#else
#include "platform_posix.h"
#endif
