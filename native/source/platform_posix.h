/* POSIX loader and UTF-16 configuration helpers shared by Linux and macOS. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <time.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <pthread.h>
#include <spawn.h>
#include <sys/wait.h>
#include <fcntl.h>
typedef uint32_t U;
typedef uint16_t W;
typedef void *Handle;
static void widecopy(W*d,const W*s,U capacity){U i=0;while(i+1<capacity&&s[i]){d[i]=s[i];i++;}d[i]=0;}
static void textwide(W*d,const char*s,U capacity){U n=0;const unsigned char*p=(const unsigned char*)s;while(*p&&n+2<capacity){U c=*p++;if(c>=0xf0){c=(c&7)<<18;c|=(*p++&63)<<12;c|=(*p++&63)<<6;c|=*p++&63;}else if(c>=0xe0){c=(c&15)<<12;c|=(*p++&63)<<6;c|=*p++&63;}else if(c>=0xc0){c=(c&31)<<6;c|=*p++&63;}if(c>65535){c-=65536;d[n++]=0xd800+(c>>10);c=0xdc00+(c&1023);}d[n++]=c;}d[n]=0;}
static void narrow(char*d,const W*s,U capacity){U n=0;while(*s&&n+4<capacity){U c=*s++;if(c>=0xd800&&c<=0xdbff&&*s>=0xdc00&&*s<=0xdfff)c=65536+((c-0xd800)<<10)+(*s++-0xdc00);if(c<128)d[n++]=c;else if(c<2048){d[n++]=0xc0|(c>>6);d[n++]=0x80|(c&63);}else if(c<65536){d[n++]=0xe0|(c>>12);d[n++]=0x80|((c>>6)&63);d[n++]=0x80|(c&63);}else{d[n++]=0xf0|(c>>18);d[n++]=0x80|((c>>12)&63);d[n++]=0x80|((c>>6)&63);d[n++]=0x80|(c&63);}}d[n]=0;}
static Handle module;
static U GetModuleFileNameW(Handle unused,W*out,U capacity){Dl_info info;if(!dladdr((void*)&GetModuleFileNameW,&info)||!info.dli_fname)return 0;textwide(out,info.dli_fname,capacity);U n=0;while(out[n])n++;return n;}
static Handle CreateFileW(const W*path,U access,U share,Handle security,U disposition,U flags,Handle template){char name[16388];narrow(name,path,sizeof(name));FILE*f=fopen(name,"rb");return f?(Handle)f:(Handle)-1;}
static U GetFileSize(Handle file,U*unused){FILE*f=file;long pos=ftell(f);if(fseek(f,0,SEEK_END))return 0;long size=ftell(f);fseek(f,pos,SEEK_SET);return size<0?0:(U)size;}
static int ReadFile(Handle file,void*data,U size,U*read,Handle unused){*read=fread(data,1,size,file);return !ferror((FILE*)file);}
static int CloseHandle(Handle file){return fclose(file)==0;}
static int valid_normalized(double value){return value>=0&&value<=1;}
static uint64_t GetTickCount64(void){struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);return (uint64_t)ts.tv_sec*1000+ts.tv_nsec/1000000;}
