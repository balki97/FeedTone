/* Configured transport only: DSP belongs to the private Python graph service. */
#define MAX_PARAMS 256
#define IO_FRAMES 65536
#define SERVICE_MAGIC 0x53534652u
typedef struct {U id,steps;double initial,minimum,maximum;W name[128],units[128];} Parameter;
typedef struct {U flags,count;char processorUID[16],controllerUID[16];W title[128],vendor[64],app[4097],command[4097],cwd[4097];Parameter parameters[MAX_PARAMS];} Configuration;
static Configuration config;
static int configuration_status;
static W configpath[4097];
static U take_u32(unsigned char **cursor,unsigned char*end,int*ok) {U v=0;if((size_t)(end-*cursor)<4){*ok=0;return 0;}memcpy(&v,*cursor,4);*cursor+=4;return v;}
static double take_double(unsigned char **cursor,unsigned char*end,int*ok) {double v=0;if((size_t)(end-*cursor)<8){*ok=0;return 0;}memcpy(&v,*cursor,8);*cursor+=8;return v;}
static void take_string(unsigned char **cursor,unsigned char*end,W*out,U capacity,int*ok) {U n=take_u32(cursor,end,ok);if(!*ok||n>=capacity||n>(U)(end-*cursor)/2){*ok=0;return;}memcpy(out,*cursor,n*2);out[n]=0;*cursor+=n*2;for(U i=0;i<n;i++)if(!out[i])*ok=0;}
static int load_configuration(void) {
 if(configuration_status)return configuration_status==1;
 configuration_status=-1;U n=GetModuleFileNameW(module,configpath,4096);if(!n||n>=4096)return 0;
 while(n&&configpath[n-1]!='\\'&&configpath[n-1]!='/')n--;configpath[n]=0;
#ifndef _WIN32
 for(int level=0;level<3;level++){if(n)n--;while(n&&configpath[n-1]!='/')n--;}
#endif
 const char*s="feedtone-vst.config.bin";while(*s&&n<4096)configpath[n++]=(unsigned char)*s++;configpath[n]=0;if(*s)return 0;
 Handle file=CreateFileW(configpath,0x80000000,1,NULL,3,0,NULL);if(file==(Handle)-1)return 0;
 U size=GetFileSize(file,NULL),read=0;if(size<56||size>1048576){CloseHandle(file);return 0;}
 unsigned char*raw=malloc(size);if(!raw){CloseHandle(file);return 0;}
 int ok=ReadFile(file,raw,size,&read,NULL)&&read==size;CloseHandle(file);unsigned char*c=raw,*end=raw+size;
 U magic=take_u32(&c,end,&ok),version=take_u32(&c,end,&ok);config.flags=take_u32(&c,end,&ok);config.count=take_u32(&c,end,&ok);
 U state=take_u32(&c,end,&ok),reserved=take_u32(&c,end,&ok);
 if(magic!=0x46545352||version!=1||config.flags>1||config.count>MAX_PARAMS||state!=1||reserved||end-c<32)ok=0;
 if(ok){memcpy(config.processorUID,c,16);memcpy(config.controllerUID,c+16,16);c+=32;}
 take_string(&c,end,config.title,128,&ok);take_string(&c,end,config.vendor,64,&ok);take_string(&c,end,config.app,4097,&ok);take_string(&c,end,config.command,4097,&ok);take_string(&c,end,config.cwd,4097,&ok);
 for(U i=0;ok&&i<config.count;i++){Parameter*p=&config.parameters[i];p->id=take_u32(&c,end,&ok);p->steps=take_u32(&c,end,&ok);p->initial=take_double(&c,end,&ok);p->minimum=take_double(&c,end,&ok);p->maximum=take_double(&c,end,&ok);take_string(&c,end,p->name,128,&ok);take_string(&c,end,p->units,128,&ok);
  if(!valid_normalized(p->initial)||!(p->minimum<=p->maximum)||!(p->minimum>=-1e308&&p->maximum<=1e308)||p->steps>0x7fffffff)ok=0;
  for(U j=0;j<i;j++)if(config.parameters[j].id==p->id)ok=0;
 }
 if(c!=end||!config.title[0]||(!(config.flags&1)&&(!config.app[0]||!config.command[0])))ok=0;
 free(raw);if(ok)configuration_status=1;return ok;
}
static int parameter_index(U id) {for(U i=0;i<config.count;i++)if(config.parameters[i].id==id)return (int)i;return -1;}
#ifdef _WIN32
typedef struct {U length;Handle descriptor;int inherit;} SecurityAttributes;
typedef struct {U cb;W*reserved;W*desktop;W*title;U x,y,xsize,ysize,xchars,ychars,fill,flags;uint16_t show,reservedBytes;unsigned char*reservedData;Handle input,output,error;} StartupInfo;
typedef struct {StartupInfo basic;Handle attributes;} StartupInfoEx;
typedef struct {Handle process,thread;U processID,threadID;} ProcessInfo;
typedef struct {Handle input,output,process,watchdog,stop;float*buffer;U channels,rate,latency;int failed,ready;uint64_t deadline;} Service;
/* A stalled child must not leave the host blocked indefinitely in WriteFile. */
static U __stdcall service_watchdog(void*context) {Service*s=context;while(WaitForSingleObject(s->stop,25)==258){uint64_t deadline=__atomic_load_n(&s->deadline,__ATOMIC_ACQUIRE);if(deadline&&GetTickCount64()>=deadline){TerminateProcess(s->process,1);break;}}return 0;}
static void service_deadline(Service*s,U timeout) {__atomic_store_n(&s->deadline,timeout?GetTickCount64()+timeout:0,__ATOMIC_RELEASE);}
static int pipe_write(Handle pipe,const void*data,U size) {const unsigned char*p=data;while(size){U done=0;if(!WriteFile(pipe,p,size,&done,NULL)||!done)return 0;p+=done;size-=done;}return 1;}
static int pipe_read(Handle pipe,void*data,U size,U timeout) {unsigned char*p=data;uint64_t start=GetTickCount64();while(size){U available=0;if(!PeekNamedPipe(pipe,NULL,0,NULL,&available,NULL))return 0;if(!available){if(GetTickCount64()-start>=timeout)return 0;Sleep(0);continue;}U done=0,count=available<size?available:size;if(!ReadFile(pipe,p,count,&done,NULL)||!done)return 0;p+=done;size-=done;}return 1;}
static void service_close(Service*s) {service_deadline(s,1000);if(s->input){if(s->ready&&!s->failed){U command[5]={SERVICE_MAGIC,1,4,0,0},reply[8];if(pipe_write(s->input,command,20)&&s->output)pipe_read(s->output,reply,32,1000);}CloseHandle(s->input);s->input=NULL;}if(s->output){CloseHandle(s->output);s->output=NULL;}if(s->process&&WaitForSingleObject(s->process,1000)!=0)TerminateProcess(s->process,1);if(s->stop)SetEvent(s->stop);if(s->watchdog){WaitForSingleObject(s->watchdog,1000);CloseHandle(s->watchdog);s->watchdog=NULL;}if(s->stop){CloseHandle(s->stop);s->stop=NULL;}if(s->process){CloseHandle(s->process);s->process=NULL;}free(s->buffer);s->buffer=NULL;s->ready=0;s->channels=s->rate=0;}
static int response(Service*s,U operation,U expectedFrames,U expectedChannels,U timeout) {U words[8];if(!pipe_read(s->output,words,32,timeout)||words[0]!=SERVICE_MAGIC||words[1]!=1||words[2]!=operation||words[3]!=0)return 0;if(operation==1&&(words[4]!=expectedFrames||words[5]!=expectedChannels))return 0;s->latency=words[7];return 1;}
static int service_command(Service*s,U operation,U arg0,U arg1,const void*payload,U size) {if(s->failed)return 0;service_deadline(s,operation==7?30000:5000);U words[5]={SERVICE_MAGIC,1,operation,arg0,arg1};if(!pipe_write(s->input,words,20)||(size&&!pipe_write(s->input,payload,size))||!response(s,operation,arg0,arg1,operation==7?30000:5000)){s->failed=1;return 0;}service_deadline(s,0);return 1;}
static int service_start(Service*s) {
 if(s->ready)return !s->failed;if(s->failed)return 0;
 if(config.flags&1){s->ready=1;return 1;}
 SecurityAttributes security={sizeof(SecurityAttributes),NULL,1};Handle childInput=NULL,childOutput=NULL,log=NULL;
 if(!CreatePipe(&childInput,&s->input,&security,65536)||!CreatePipe(&s->output,&childOutput,&security,65536))goto fail;
 if(!SetHandleInformation(s->input,1,0)||!SetHandleInformation(s->output,1,0))goto fail;
 W logpath[512];U n=GetTempPathW(450,logpath);if(!n||n>450)goto fail;
 const char*prefix="FeedToneVST-";while(*prefix)logpath[n++]=*prefix++;U pid=GetCurrentProcessId();const char*hex="0123456789abcdef";for(int i=7;i>=0;i--)logpath[n++]=hex[(pid>>(i*4))&15];logpath[n++]='-';U tick=(U)GetTickCount64();for(int i=7;i>=0;i--)logpath[n++]=hex[(tick>>(i*4))&15];textwide(logpath+n,".log",8);
 log=CreateFileW(logpath,0x40000000,3,&security,2,0,NULL);if(log==(Handle)-1){log=NULL;goto fail;}
 StartupInfoEx startup;memset(&startup,0,sizeof(startup));startup.basic.cb=sizeof(startup);startup.basic.flags=0x101;startup.basic.show=0;startup.basic.input=childInput;startup.basic.output=childOutput;startup.basic.error=log;
 size_t attributeSize=0;InitializeProcThreadAttributeList(NULL,1,0,&attributeSize);startup.attributes=malloc(attributeSize);if(!startup.attributes)goto fail;
 if(!InitializeProcThreadAttributeList(startup.attributes,1,0,&attributeSize)){free(startup.attributes);goto fail;}
 Handle allowed[3]={childInput,childOutput,log};if(!UpdateProcThreadAttribute(startup.attributes,0,0x20002,allowed,sizeof(allowed),NULL,NULL)){DeleteProcThreadAttributeList(startup.attributes);free(startup.attributes);goto fail;}
 ProcessInfo process;W*command=malloc(8194);if(!command){DeleteProcThreadAttributeList(startup.attributes);free(startup.attributes);goto fail;}widecopy(command,config.command,4097);
 int created=CreateProcessW(config.app,command,NULL,NULL,1,0x08080000,NULL,config.cwd[0]?config.cwd:NULL,&startup,&process);free(command);DeleteProcThreadAttributeList(startup.attributes);free(startup.attributes);
 if(!created)goto fail;s->process=process.process;CloseHandle(process.thread);CloseHandle(childInput);childInput=NULL;CloseHandle(childOutput);childOutput=NULL;CloseHandle(log);log=NULL;
 s->stop=CreateEventW(NULL,1,0,NULL);if(!s->stop)goto fail;s->watchdog=CreateThread(NULL,0,service_watchdog,s,0,NULL);if(!s->watchdog)goto fail;service_deadline(s,30000);
 s->buffer=malloc(IO_FRAMES*2*4);if(!s->buffer||!response(s,0,0,0,30000))goto fail;service_deadline(s,0);s->ready=1;return 1;
fail:if(childInput)CloseHandle(childInput);if(childOutput)CloseHandle(childOutput);if(log)CloseHandle(log);s->failed=1;service_close(s);return 0;
}
static int service_configure(Service*s,U rate,U channels) {if(!service_start(s))return 0;if(s->rate==rate&&s->channels==channels)return 1;if(!(config.flags&1)&&!service_command(s,7,rate,channels,NULL,0))return 0;s->rate=rate;s->channels=channels;return 1;}
static int service_parameter(Service*s,U id,double value) {int index=parameter_index(id);if(index<0)return 0;if(config.flags&1)return 1;return service_command(s,2,(U)index,8,&value,8);}
static int service_reset(Service*s) {if(config.flags&1)return 1;return !s->ready||service_command(s,3,0,0,NULL,0);}

#else
#include "service_posix.h"
#endif
