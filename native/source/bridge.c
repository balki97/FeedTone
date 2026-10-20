//------------------------------------------------------------------------
// Flags       : clang-format SMTGSequencer
// Project     : VST3 C API Generator
// Filename    : cgain.c
// Created by  : nzorn, 07/2022
// Description : Example VST3 Plug-in using the C API
//------------------------------------------------------------------------

//-----------------------------------------------------------------------------
// This file is part of a Steinberg SDK. It is subject to the license terms
// in the LICENSE file found in the top-level directory of this distribution
// and at www.steinberg.net/sdklicenses.
// No part of the SDK, including this file, may be copied, modified, propagated,
// or distributed except according to the terms contained in the LICENSE file.
//-----------------------------------------------------------------------------


#include "platform.h"
#include "vendor/vst3_c_api.h"
#include "bridge_runtime.h"

static size_t pointerOffset = sizeof (void*);

int compare_iid (const Steinberg_TUID id1, const Steinberg_TUID id2)
{
	return memcmp (id1, id2, sizeof (Steinberg_TUID)) == 0;
}

#define audioProcessorUID config.processorUID

#define editControllerUID config.controllerUID

struct AGainAudioProcessorVtbl
{
	Steinberg_Vst_IComponentVtbl component;
	Steinberg_Vst_IConnectionPointVtbl connectionPoint;
	Steinberg_Vst_IAudioProcessorVtbl audioProcessor;
	Steinberg_Vst_IProcessContextRequirementsVtbl processContextRequirements;
};

typedef struct
{
	const struct Steinberg_Vst_IComponentVtbl* componentVtbl;
	const struct Steinberg_Vst_IConnectionPointVtbl* connectionPointVtbl;
	const struct Steinberg_Vst_IAudioProcessorVtbl* audioProcessorVtbl;
	const struct Steinberg_Vst_IProcessContextRequirementsVtbl* processContextRequirementsVtbl;
	Steinberg_int32 refCount;
	struct Steinberg_Vst_IConnectionPoint* connectionPoint;
	double values[MAX_PARAMS];
 Service service;
 U channels,rate,maxFrames;
 int dirty;
 struct {int offset,index;double value;} events[4096];
} AGainAudioProcessor;

struct AGainEditControllerVtbl
{
	Steinberg_Vst_IEditControllerVtbl editController;
	Steinberg_Vst_IConnectionPointVtbl connectionPoint;
	Steinberg_Vst_IEditController2Vtbl editController2;
};

typedef struct
{
	const struct Steinberg_Vst_IEditControllerVtbl* editControllerVtbl;
	const struct Steinberg_Vst_IConnectionPointVtbl* connectionPointVtbl;
	const struct Steinberg_Vst_IEditController2Vtbl* editController2Vtbl;
	Steinberg_int32 refCount;
	double values[MAX_PARAMS];
 struct Steinberg_Vst_IHostApplication* host;
 struct Steinberg_Vst_IConnectionPoint* peer;
} AGainEditController;

struct AGainFactoryVtbl
{
	Steinberg_IPluginFactory2Vtbl pluginFactory;
};

typedef struct
{
	const struct Steinberg_IPluginFactory2Vtbl* pluginFactoryVtbl;
	struct Steinberg_PClassInfo2 classes[2];
	struct Steinberg_PFactoryInfo factoryInfo;
} AGainFactory;


static void controller_sync(AGainEditController*s,U id,double value) {
 if(!s->host||!s->peer)return;struct Steinberg_Vst_IMessage*message=NULL;
 Steinberg_TUID iid;memcpy(iid,Steinberg_Vst_IMessage_iid,16);
 if(s->host->lpVtbl->createInstance(s->host,iid,iid,(void**)&message)||!message)return;
 message->lpVtbl->setMessageID(message,"FeedToneSourceControl");struct Steinberg_Vst_IAttributeList*attributes=message->lpVtbl->getAttributes(message);
 if(attributes&&!attributes->lpVtbl->setInt(attributes,"id",id)&&!attributes->lpVtbl->setFloat(attributes,"value",value))s->peer->lpVtbl->notify(s->peer,message);
 message->lpVtbl->release(message);
}
static int state_read(struct Steinberg_IBStream*stream,double*values) {
 if(!stream)return 0;U header[3];Steinberg_int32 done;
 if(stream->lpVtbl->read(stream,header,12,&done)||done!=12||header[0]!=0x53545352||header[1]!=1||header[2]!=config.count)return 0;
 double incoming[MAX_PARAMS];for(U i=0;i<config.count;i++){U id;if(stream->lpVtbl->read(stream,&id,4,&done)||done!=4||id!=config.parameters[i].id||stream->lpVtbl->read(stream,&incoming[i],8,&done)||done!=8||!valid_normalized(incoming[i]))return 0;}
 memcpy(values,incoming,config.count*8);return 1;
}
static int state_write(struct Steinberg_IBStream*stream,double*values) {
 if(!stream)return 0;U header[3]={0x53545352,1,config.count};Steinberg_int32 done;
 if(stream->lpVtbl->write(stream,header,12,&done)||done!=12)return 0;
 for(U i=0;i<config.count;i++)if(stream->lpVtbl->write(stream,&config.parameters[i].id,4,&done)||done!=4||stream->lpVtbl->write(stream,&values[i],8,&done)||done!=8)return 0;return 1;
}

/* Audio Processor Methods */

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_AddRef (void* thisInterface)
{
AGainAudioProcessor*s=thisInterface;return __atomic_add_fetch(&s->refCount,1,__ATOMIC_RELAXED);
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_AddRef_ConnectionPoint (void* thisInterface)
{
	return AGainProcessor_AddRef ((void*)((int64_t)thisInterface - pointerOffset));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_AddRef_AudioProcessor (void* thisInterface)
{
	return AGainProcessor_AddRef ((void*)((int64_t)thisInterface - (pointerOffset * 2)));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE
AGainProcessor_AddRef_ProcessContextRequirements (void* thisInterface)
{
	return AGainProcessor_AddRef ((void*)((int64_t)thisInterface - (pointerOffset * 3)));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_Release (void* thisInterface)
{
AGainAudioProcessor*s=thisInterface;int count=__atomic_sub_fetch(&s->refCount,1,__ATOMIC_ACQ_REL);if(!count){service_close(&s->service);free(s);}return count;
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_Release_ConnectionPoint (void* thisInterface)
{
	return AGainProcessor_Release ((void*)((int64_t)thisInterface - pointerOffset));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_Release_AudioProcessor (void* thisInterface)
{
	return AGainProcessor_Release ((void*)((int64_t)thisInterface - (pointerOffset * 2)));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE
AGainProcessor_Release_ProcessContextRequirements (void* thisInterface)
{
	return AGainProcessor_Release ((void*)((int64_t)thisInterface - (pointerOffset * 3)));
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_QueryInterface (void* thisInterface,
                                                                        const Steinberg_TUID iid,
                                                                        void** obj)
{
	AGainAudioProcessor* instance = (AGainAudioProcessor*)thisInterface;
	if (compare_iid (Steinberg_FUnknown_iid, iid))
	{
		AGainProcessor_AddRef (thisInterface);
		*obj = instance;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_IPluginBase_iid, iid))
	{
		AGainProcessor_AddRef (thisInterface);
		*obj = instance;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IComponent_iid, iid))
	{
		AGainProcessor_AddRef (thisInterface);
		*obj = instance;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IConnectionPoint_iid, iid))
	{
		AGainProcessor_AddRef (thisInterface);
		*obj = (void*)((int64_t)instance + pointerOffset);
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IAudioProcessor_iid, iid))
	{
		AGainProcessor_AddRef (thisInterface);
		*obj = (void*)((int64_t)instance + (pointerOffset * 2));
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IProcessContextRequirements_iid, iid))
	{
		AGainProcessor_AddRef (thisInterface);
		*obj = (void*)((int64_t)instance + (pointerOffset * 3));
		return Steinberg_kResultTrue;
	}
	*obj = NULL;
	return Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_QueryInterface_ConnectionPoint (
    void* thisInterface, const Steinberg_TUID iid, void** obj)
{
	return AGainProcessor_QueryInterface ((void*)((int64_t)thisInterface - pointerOffset), iid,
	                                      obj);
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_QueryInterface_AudioProcessor (
    void* thisInterface, const Steinberg_TUID iid, void** obj)
{
	return AGainProcessor_QueryInterface ((void*)((int64_t)thisInterface - (pointerOffset * 2)),
	                                      iid, obj);
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_QueryInterface_ProcessContextRequirements (
    void* thisInterface, const Steinberg_TUID iid, void** obj)
{
	return AGainProcessor_QueryInterface ((void*)((int64_t)thisInterface - (pointerOffset * 3)),
	                                      iid, obj);
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_Initialize (void* thisInterface, struct Steinberg_FUnknown* context)
{
return load_configuration()?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_Terminate (void* thisInterface)
{
AGainAudioProcessor*s=thisInterface;service_close(&s->service);return Steinberg_kResultOk;
};

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_Connect (void* thisInterface, struct Steinberg_Vst_IConnectionPoint* other)
{
	AGainAudioProcessor* instance = (AGainAudioProcessor*)((int64_t)thisInterface - pointerOffset);
	instance->connectionPoint = other;
	return Steinberg_kResultTrue;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_Disconnect (void* thisInterface, struct Steinberg_Vst_IConnectionPoint* other)
{
	AGainAudioProcessor* instance = (AGainAudioProcessor*)((int64_t)thisInterface - pointerOffset);
	instance->connectionPoint = NULL;
	return Steinberg_kResultTrue;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_Notify (void* thisInterface, struct Steinberg_Vst_IMessage* message)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset);if(!message)return Steinberg_kInvalidArgument;const char*name=message->lpVtbl->getMessageID(message);if(!name||strcmp(name,"FeedToneSourceControl"))return Steinberg_kResultFalse;
struct Steinberg_Vst_IAttributeList*a=message->lpVtbl->getAttributes(message);Steinberg_int64 id;double value;if(!a||a->lpVtbl->getInt(a,"id",&id)||a->lpVtbl->getFloat(a,"value",&value)||!valid_normalized(value))return Steinberg_kInvalidArgument;int i=parameter_index((U)id);if(i<0)return Steinberg_kInvalidArgument;__atomic_store(&s->values[i],&value,__ATOMIC_RELEASE);__atomic_store_n(&s->dirty,1,__ATOMIC_RELEASE);return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_GetControllerClassId (void* thisInterface, Steinberg_TUID classId)
{
	memcpy (classId, editControllerUID, sizeof (Steinberg_TUID));
	return Steinberg_kResultTrue;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_SetIoMode (void* thisInterface,
                                                                   Steinberg_Vst_IoMode mode)
{
	return Steinberg_kResultOk;
};

Steinberg_int32 SMTG_STDMETHODCALLTYPE AGainProcessor_GetBusCount (void* thisInterface,
                                                                   Steinberg_Vst_MediaType type,
                                                                   Steinberg_Vst_BusDirection dir)
{
	if (type == Steinberg_Vst_MediaTypes_kAudio)
	{
		return 1;
	}
	return 0;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_GetBusInfo (
    void* thisInterface, Steinberg_Vst_MediaType type, Steinberg_Vst_BusDirection dir,
    Steinberg_int32 index, struct Steinberg_Vst_BusInfo* bus)
{
if(!bus||index||type!=Steinberg_Vst_MediaTypes_kAudio)return Steinberg_kInvalidArgument;
AGainAudioProcessor*s=thisInterface;memset(bus,0,sizeof(*bus));textwide((W*)bus->name,dir==0?"Input":"Output",128);
bus->channelCount=s->channels;bus->flags=Steinberg_Vst_BusInfo_BusFlags_kDefaultActive;bus->direction=dir;bus->mediaType=type;bus->busType=Steinberg_Vst_BusTypes_kMain;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_GetRoutingInfo (void* thisInterface, struct Steinberg_Vst_RoutingInfo* inInfo,
                               struct Steinberg_Vst_RoutingInfo* outInfo)
{
	return Steinberg_kNotImplemented;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_ActivateBus (void* thisInterface,
                                                                     Steinberg_Vst_MediaType type,
                                                                     Steinberg_Vst_BusDirection dir,
                                                                     Steinberg_int32 index,
                                                                     Steinberg_TBool state)
{
	if (type == Steinberg_Vst_MediaTypes_kEvent)
	{
		return Steinberg_kResultFalse;
	}
	return Steinberg_kResultTrue;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_SetActive (void* thisInterface,
                                                                   Steinberg_TBool state)
{
AGainAudioProcessor*s=thisInterface;if(state)return s->maxFrames&&service_configure(&s->service,s->rate,s->channels)?Steinberg_kResultOk:Steinberg_kResultFalse;
s->dirty=1;return service_reset(&s->service)?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_SetState (void* thisInterface,
                                                                  struct Steinberg_IBStream* state)
{
AGainAudioProcessor*s=thisInterface;if(!state_read(state,s->values))return Steinberg_kResultFalse;s->dirty=1;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_GetState (void* thisInterface,
                                                                  struct Steinberg_IBStream* state)
{
AGainAudioProcessor*s=thisInterface;return state_write(state,s->values)?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_SetBusArrangements (
    void* thisInterface, Steinberg_Vst_SpeakerArrangement* inputs, Steinberg_int32 numIns,
    Steinberg_Vst_SpeakerArrangement* outputs, Steinberg_int32 numOuts)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset*2);
if(!inputs||!outputs||numIns!=1||numOuts!=1||inputs[0]!=outputs[0]||(inputs[0]!=Steinberg_Vst_SpeakerArr_kStereo&&inputs[0]!=Steinberg_Vst_SpeakerArr_kMono))return Steinberg_kResultFalse;
U channels=inputs[0]==Steinberg_Vst_SpeakerArr_kMono?1:2;
if(s->service.ready&&!service_configure(&s->service,s->rate,channels))return Steinberg_kResultFalse;s->channels=channels;s->dirty=1;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_GetBusArrangement (void* thisInterface, Steinberg_Vst_BusDirection dir,
                                  Steinberg_int32 index, Steinberg_Vst_SpeakerArrangement* arr)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset*2);if(index||!arr)return Steinberg_kInvalidArgument;
*arr=s->channels==1?Steinberg_Vst_SpeakerArr_kMono:Steinberg_Vst_SpeakerArr_kStereo;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_CanProcessSampleSize (void* thisInterface, Steinberg_int32 symbolicSampleSize)
{
	return symbolicSampleSize == Steinberg_Vst_SymbolicSampleSizes_kSample32 ?
	           Steinberg_kResultTrue :
	           Steinberg_kResultFalse;
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_GetLatencySamples (void* thisInterface)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset*2);return config.flags&1?0:s->service.latency;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_SetupProcessing (void* thisInterface, struct Steinberg_Vst_ProcessSetup* setup)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset*2);
if(!setup||setup->symbolicSampleSize!=Steinberg_Vst_SymbolicSampleSizes_kSample32||setup->sampleRate!=48000||setup->maxSamplesPerBlock<1||setup->maxSamplesPerBlock>IO_FRAMES)return Steinberg_kResultFalse;
s->rate=48000;s->maxFrames=setup->maxSamplesPerBlock;return service_configure(&s->service,s->rate,s->channels)?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainProcessor_SetProcessing (void* thisInterface,
                                                                       Steinberg_TBool state)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset*2);if(!state){s->dirty=1;return service_reset(&s->service)?Steinberg_kResultOk:Steinberg_kResultFalse;}return s->service.ready&&!s->service.failed?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainProcessor_Process (void* thisInterface, struct Steinberg_Vst_ProcessData* data)
{
AGainAudioProcessor*s=(void*)((char*)thisInterface-pointerOffset*2);
if(!data||data->numSamples<0||(U)data->numSamples>s->maxFrames||data->symbolicSampleSize!=Steinberg_Vst_SymbolicSampleSizes_kSample32)return Steinberg_kInvalidArgument;
U frames=data->numSamples,channels=s->channels,eventCount=0;
if(data->inputParameterChanges){struct Steinberg_Vst_IParameterChanges*changes=data->inputParameterChanges;int count=changes->lpVtbl->getParameterCount(changes);if(count<0||count>MAX_PARAMS)return Steinberg_kInvalidArgument;
 for(int i=0;i<count;i++){struct Steinberg_Vst_IParamValueQueue*q=changes->lpVtbl->getParameterData(changes,i);if(!q)continue;int index=parameter_index(q->lpVtbl->getParameterId(q));if(index<0)continue;int points=q->lpVtbl->getPointCount(q);if(points<0||points>4096-(int)eventCount)return Steinberg_kInvalidArgument;
  for(int j=0;j<points;j++){int offset;double value;if(q->lpVtbl->getPoint(q,j,&offset,&value)||offset<0||(U)offset>frames||!valid_normalized(value))return Steinberg_kInvalidArgument;U n=eventCount++;while(n&&s->events[n-1].offset>offset){s->events[n]=s->events[n-1];n--;}s->events[n].offset=offset;s->events[n].index=index;s->events[n].value=value;}
 }}
if(__atomic_exchange_n(&s->dirty,0,__ATOMIC_ACQ_REL)){for(U i=0;i<config.count;i++){double value;__atomic_load(&s->values[i],&value,__ATOMIC_ACQUIRE);if(!service_parameter(&s->service,config.parameters[i].id,value))goto failure;}}
if(!frames){for(U i=0;i<eventCount;i++){int index=s->events[i].index;s->values[index]=s->events[i].value;if(!service_parameter(&s->service,config.parameters[index].id,s->values[index]))goto failure;}return Steinberg_kResultOk;}
if(!s->service.ready||s->service.failed||data->numInputs!=1||data->numOutputs!=1||!data->inputs||!data->outputs||data->inputs[0].numChannels!=(int)channels||data->outputs[0].numChannels!=(int)channels)goto failure;
for(U c=0;c<channels;c++)if(!data->inputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c]||!data->outputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c])goto failure;
U position=0,event=0;while(position<frames||event<eventCount){while(event<eventCount&&(U)s->events[event].offset==position){int index=s->events[event].index;s->values[index]=s->events[event].value;if(!service_parameter(&s->service,config.parameters[index].id,s->values[index]))goto failure;event++;}
 U end=event<eventCount?(U)s->events[event].offset:frames;if(end==position)continue;U length=end-position;
 if(config.flags&1){for(U c=0;c<channels;c++)for(U i=position;i<end;i++)data->outputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c][i]=data->inputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c][i];}
 else {for(U i=0;i<length;i++)for(U c=0;c<channels;c++)s->service.buffer[i*channels+c]=data->inputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c][position+i];U command[5]={SERVICE_MAGIC,1,1,length,0};
 service_deadline(&s->service,5000);if(!pipe_write(s->service.input,command,20)||!pipe_write(s->service.input,s->service.buffer,length*channels*4)||!response(&s->service,1,length,channels,5000)||!pipe_read(s->service.output,s->service.buffer,length*channels*4,5000))goto failure;service_deadline(&s->service,0);
 for(U i=0;i<length;i++)for(U c=0;c<channels;c++)data->outputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c][position+i]=s->service.buffer[i*channels+c];}
 position=end;
}
data->outputs[0].silenceFlags=0;return Steinberg_kResultOk;
failure:s->service.failed=1;if(data&&data->outputs&&data->numOutputs>0)for(int c=0;c<data->outputs[0].numChannels;c++)if(data->outputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c])memset(data->outputs[0].Steinberg_Vst_AudioBusBuffers_channelBuffers32[c],0,frames*4);return Steinberg_kResultFalse;
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainProcessor_GetTailSamples (void* thisInterface)
{
return config.flags&1?0:0xffffffffu;
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE
AGainProcessor_getProcessContextRequirements (void* thisInterface)
{
	return 0;
}

/*-----------------------------------------------------------------------------------------------------------------------------
Edit Controller methods*/

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainController_AddRef (void* thisInterface)
{
AGainEditController*s=thisInterface;return __atomic_add_fetch(&s->refCount,1,__ATOMIC_RELAXED);
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainController_AddRef_ConnectionPoint (void* thisInterface)
{
	return AGainController_AddRef ((void*)((int64_t)thisInterface - pointerOffset));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainController_AddRef_EditController2 (void* thisInterface)
{
	return AGainController_AddRef ((void*)((int64_t)thisInterface - (pointerOffset * 2)));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainController_Release (void* thisInterface)
{
AGainEditController*s=thisInterface;int count=__atomic_sub_fetch(&s->refCount,1,__ATOMIC_ACQ_REL);if(!count){if(s->host)s->host->lpVtbl->release(s->host);free(s);}return count;
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE
AGainController_Release_ConnectionPoint (void* thisInterface)
{
	return AGainController_Release ((void*)((int64_t)thisInterface - pointerOffset));
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE
AGainController_Release_EditController2 (void* thisInterface)
{
	return AGainController_Release ((void*)((int64_t)thisInterface - (pointerOffset * 2)));
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_QueryInterface (void* thisInterface,
                                                                         const Steinberg_TUID iid,
                                                                         void** obj)
{
	AGainEditController* instance = (AGainEditController*)thisInterface;
	if (compare_iid (Steinberg_FUnknown_iid, iid))
	{
		AGainController_AddRef (thisInterface);
		*obj = instance;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_IPluginBase_iid, iid))
	{
		AGainController_AddRef (thisInterface);
		*obj = instance;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IEditController_iid, iid))
	{
		AGainController_AddRef (thisInterface);
		*obj = instance;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IConnectionPoint_iid, iid))
	{
		AGainController_AddRef (thisInterface);
		*obj = (void*)((int64_t)instance + pointerOffset);
		return Steinberg_kResultTrue;
	}
	if (compare_iid (Steinberg_Vst_IEditController2_iid, iid))
	{
		AGainController_AddRef (thisInterface);
		*obj = (void*)((int64_t)instance + (pointerOffset * 2));
		return Steinberg_kResultTrue;
	}
	*obj = NULL;
	return Steinberg_kNoInterface;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_QueryInterface_ConnectionPoint (
    void* thisInterface, const Steinberg_TUID iid, void** obj)
{
	return AGainController_QueryInterface ((void*)((int64_t)thisInterface - pointerOffset), iid,
	                                       obj);
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_QueryInterface_EditController2 (
    void* thisInterface, const Steinberg_TUID iid, void** obj)
{
	return AGainController_QueryInterface ((void*)((int64_t)thisInterface - (pointerOffset * 2)),
	                                       iid, obj);
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainController_Initialize (void* thisInterface, struct Steinberg_FUnknown* context)
{
AGainEditController*s=thisInterface;if(context)context->lpVtbl->queryInterface(context,Steinberg_Vst_IHostApplication_iid,(void**)&s->host);return load_configuration()?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_Terminate (void* thisInterface)
{
AGainEditController*s=thisInterface;if(s->host){s->host->lpVtbl->release(s->host);s->host=NULL;}s->peer=NULL;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainController_Connect (void* thisInterface, struct Steinberg_Vst_IConnectionPoint* other)
{
AGainEditController*s=(void*)((char*)thisInterface-pointerOffset);s->peer=other;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainController_Disconnect (void* thisInterface, struct Steinberg_Vst_IConnectionPoint* other)
{
AGainEditController*s=(void*)((char*)thisInterface-pointerOffset);s->peer=NULL;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainController_Notify (void* thisInterface, struct Steinberg_Vst_IMessage* message)
{
	return Steinberg_kNotImplemented;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainController_SetComponentState (void* thisInterface, struct Steinberg_IBStream* state)
{
AGainEditController*s=thisInterface;return state_read(state,s->values)?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_SetState (void* thisInterface,
                                                                   struct Steinberg_IBStream* state)
{
AGainEditController*s=thisInterface;return state_read(state,s->values)?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_GetState (void* thisInterface,
                                                                   struct Steinberg_IBStream* state)
{
AGainEditController*s=thisInterface;return state_write(state,s->values)?Steinberg_kResultOk:Steinberg_kResultFalse;
}

Steinberg_int32 SMTG_STDMETHODCALLTYPE AGainController_GetParameterCount (void* thisInterface)
{
return config.count;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_GetParameterInfo (
    void* thisInterface, Steinberg_int32 paramIndex, struct Steinberg_Vst_ParameterInfo* info)
{
if(!info||paramIndex<0||(U)paramIndex>=config.count)return Steinberg_kInvalidArgument;
Parameter*p=&config.parameters[paramIndex];memset(info,0,sizeof(*info));info->id=p->id;info->stepCount=p->steps;info->defaultNormalizedValue=p->initial;info->flags=Steinberg_Vst_ParameterInfo_ParameterFlags_kCanAutomate;info->unitId=Steinberg_Vst_kRootUnitId;widecopy((W*)info->title,p->name,128);widecopy((W*)info->shortTitle,p->name,128);widecopy((W*)info->units,p->units,128);return Steinberg_kResultOk;
}

Steinberg_Vst_ParamValue SMTG_STDMETHODCALLTYPE AGainController_NormalizedParamToPlain (
    void* thisInterface, Steinberg_Vst_ParamID id, Steinberg_Vst_ParamValue valueNormalized)
{
int i=parameter_index(id);if(i<0)return 0;Parameter*p=&config.parameters[i];return p->minimum+valueNormalized*(p->maximum-p->minimum);
}

Steinberg_Vst_ParamValue SMTG_STDMETHODCALLTYPE AGainController_PlainParamToNormalized (
    void* thisInterface, Steinberg_Vst_ParamID id, Steinberg_Vst_ParamValue plainValue)
{
int i=parameter_index(id);if(i<0)return 0;Parameter*p=&config.parameters[i];if(p->minimum==p->maximum)return 0;double v=(plainValue-p->minimum)/(p->maximum-p->minimum);return v<0?0:v>1?1:v;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_GetParamStringByValue (
    void* thisInterface, Steinberg_Vst_ParamID id, Steinberg_Vst_ParamValue valueNormalized,
    Steinberg_Vst_String128 string)
{
if(!string||parameter_index(id)<0||!valid_normalized(valueNormalized))return Steinberg_kInvalidArgument;
double v=AGainController_NormalizedParamToPlain(thisInterface,id,valueNormalized);U n=0;if(v<0){string[n++]='-';v=-v;}if(v>1e12)return Steinberg_kInvalidArgument;
uint64_t fixed=(uint64_t)(v*1000.0+0.5),integer=fixed/1000;W reverse[32];U length=0;do{reverse[length++]='0'+integer%10;integer/=10;}while(integer);while(length)string[n++]=reverse[--length];string[n++]='.';U fraction=fixed%1000;string[n++]='0'+fraction/100;string[n++]='0'+fraction/10%10;string[n++]='0'+fraction%10;string[n]=0;return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_GetParamValueByString (
    void* thisInterface, Steinberg_Vst_ParamID id, Steinberg_Vst_TChar* string,
    Steinberg_Vst_ParamValue* valueNormalized)
{
if(!string||!valueNormalized||parameter_index(id)<0)return Steinberg_kInvalidArgument;double value=0,scale=1;int negative=0,dot=0,digits=0;if(*string=='-'){negative=1;string++;}
for(U i=0;string[i];i++){W c=string[i];if(c=='.'&&!dot){dot=1;continue;}if(c<'0'||c>'9'||i>30)return Steinberg_kInvalidArgument;digits++;if(dot){scale*=10;value+=(c-'0')/scale;}else value=value*10+c-'0';}if(!digits)return Steinberg_kInvalidArgument;
*valueNormalized=AGainController_PlainParamToNormalized(thisInterface,id,negative?-value:value);return Steinberg_kResultOk;
}

Steinberg_Vst_ParamValue SMTG_STDMETHODCALLTYPE
AGainController_GetParamNormalized (void* thisInterface, Steinberg_Vst_ParamID id)
{
AGainEditController*s=thisInterface;int i=parameter_index(id);return i<0?0:s->values[i];
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_SetParamNormalized (
    void* thisInterface, Steinberg_Vst_ParamID id, Steinberg_Vst_ParamValue value)
{
AGainEditController*s=thisInterface;int i=parameter_index(id);if(i<0||!valid_normalized(value))return Steinberg_kInvalidArgument;s->values[i]=value;controller_sync(s,id,value);return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_SetComponentHandler (
    void* thisInterface, struct Steinberg_Vst_IComponentHandler* handler)
{
return Steinberg_kResultOk;
}

struct Steinberg_IPlugView* SMTG_STDMETHODCALLTYPE
AGainController_CreateView (void* thisInterface, Steinberg_FIDString name)
{
	return NULL;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_SetKnobMode (void* thisInterface,
                                                                      Steinberg_Vst_KnobMode mode)
{
	return Steinberg_kNotImplemented;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_OpenHelp (void* thisInterface,
                                                                   Steinberg_TBool onlyCheck)
{
	return Steinberg_kNotImplemented;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainController_OpenAboutBox (void* thisInterface,
                                                                       Steinberg_TBool onlyCheck)
{
	return Steinberg_kNotImplemented;
}

static const struct AGainAudioProcessorVtbl kAGainAudioProcessorVtbl = {
    {AGainProcessor_QueryInterface, AGainProcessor_AddRef, AGainProcessor_Release,
     AGainProcessor_Initialize, AGainProcessor_Terminate, AGainProcessor_GetControllerClassId,
     AGainProcessor_SetIoMode, AGainProcessor_GetBusCount, AGainProcessor_GetBusInfo,
     AGainProcessor_GetRoutingInfo, AGainProcessor_ActivateBus, AGainProcessor_SetActive,
     AGainProcessor_SetState, AGainProcessor_GetState},
    {AGainProcessor_QueryInterface_ConnectionPoint, AGainProcessor_AddRef_ConnectionPoint,
     AGainProcessor_Release_ConnectionPoint, AGainProcessor_Connect, AGainProcessor_Disconnect,
     AGainProcessor_Notify},
    {AGainProcessor_QueryInterface_AudioProcessor, AGainProcessor_AddRef_AudioProcessor,
     AGainProcessor_Release_AudioProcessor, AGainProcessor_SetBusArrangements,
     AGainProcessor_GetBusArrangement, AGainProcessor_CanProcessSampleSize,
     AGainProcessor_GetLatencySamples, AGainProcessor_SetupProcessing, AGainProcessor_SetProcessing,
     AGainProcessor_Process, AGainProcessor_GetTailSamples},
    {AGainProcessor_QueryInterface_ProcessContextRequirements,
     AGainProcessor_AddRef_ProcessContextRequirements,
     AGainProcessor_Release_ProcessContextRequirements,
     AGainProcessor_getProcessContextRequirements},
};

static const struct AGainEditControllerVtbl kAGainEditControllerVtbl = {
    {AGainController_QueryInterface, AGainController_AddRef, AGainController_Release,
     AGainController_Initialize, AGainController_Terminate, AGainController_SetComponentState,
     AGainController_SetState, AGainController_GetState, AGainController_GetParameterCount,
     AGainController_GetParameterInfo, AGainController_GetParamStringByValue,
     AGainController_GetParamValueByString, AGainController_NormalizedParamToPlain,
     AGainController_PlainParamToNormalized, AGainController_GetParamNormalized,
     AGainController_SetParamNormalized, AGainController_SetComponentHandler,
     AGainController_CreateView},
    {AGainController_QueryInterface_ConnectionPoint, AGainController_AddRef_ConnectionPoint,
     AGainController_Release_ConnectionPoint, AGainController_Connect, AGainController_Disconnect,
     AGainController_Notify},
    {AGainController_QueryInterface_EditController2, AGainController_AddRef_EditController2,
     AGainController_Release_EditController2, AGainController_SetKnobMode, AGainController_OpenHelp,
     AGainController_OpenAboutBox}};

/* methods derived from "Steinberg_FUnknown": */
Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainFactory_AddRef (void* thisInterface)
{
	return 100;
}

Steinberg_uint32 SMTG_STDMETHODCALLTYPE AGainFactory_Release (void* thisInterface)
{
	return 100;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainFactory_QueryInterface (void* thisInterface,
                                                                      const Steinberg_TUID iid,
                                                                      void** obj)
{
	if (compare_iid (iid, Steinberg_FUnknown_iid))
	{
		AGainFactory_AddRef (thisInterface);
		*obj = thisInterface;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (iid, Steinberg_IPluginFactory_iid))
	{
		AGainFactory_AddRef (thisInterface);
		*obj = thisInterface;
		return Steinberg_kResultTrue;
	}
	if (compare_iid (iid, Steinberg_IPluginFactory2_iid))
	{
		AGainFactory_AddRef (thisInterface);
		*obj = thisInterface;
		return Steinberg_kResultTrue;
	}
	*obj = NULL;
	return Steinberg_kNoInterface;
}

/* methods derived from "Steinberg_IPluginFactory": */
Steinberg_tresult SMTG_STDMETHODCALLTYPE
AGainFactory_GetFactoryInfo (void* thisInterface, struct Steinberg_PFactoryInfo* info)
{
	if (info == 0)
	{
		return Steinberg_kInvalidArgument;
	}
	AGainFactory* factory = (AGainFactory*)thisInterface;
	memcpy (info, &factory->factoryInfo, sizeof (struct Steinberg_PFactoryInfo));
	return Steinberg_kResultTrue;
}

Steinberg_int32 SMTG_STDMETHODCALLTYPE AGainFactory_CountClasses (void* thisInterface)
{
	return 2;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainFactory_GetClassInfo (
    void* thisInterface, Steinberg_int32 index, struct Steinberg_PClassInfo* info)
{
if(!info||index<0||index>1)return Steinberg_kInvalidArgument;AGainFactory*f=thisInterface;memset(info,0,sizeof(*info));memcpy(info->cid,f->classes[index].cid,16);info->cardinality=f->classes[index].cardinality;strcpy(info->category,f->classes[index].category);strcpy(info->name,f->classes[index].name);return Steinberg_kResultOk;
}

Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainFactory_CreateInstance (void* thisInterface,
                                                                      Steinberg_FIDString cid,
                                                                      Steinberg_FIDString iid,
                                                                      void** obj)
{
	AGainFactory* factory = (AGainFactory*)thisInterface;
	if (compare_iid (cid, factory->classes[0].cid))
	{
		AGainAudioProcessor* instance = (AGainAudioProcessor*)malloc (sizeof (AGainAudioProcessor));
		if(!instance)return Steinberg_kOutOfMemory;
        memset(instance,0,sizeof(*instance));
		instance->componentVtbl = &kAGainAudioProcessorVtbl.component;
		instance->connectionPointVtbl = &kAGainAudioProcessorVtbl.connectionPoint;
		instance->audioProcessorVtbl = &kAGainAudioProcessorVtbl.audioProcessor;
		instance->processContextRequirementsVtbl =
		    &kAGainAudioProcessorVtbl.processContextRequirements;
		instance->refCount = 0;
		instance->connectionPoint = NULL;
		instance->channels=2;instance->rate=48000;instance->service.latency=128;instance->dirty=1;for(U i=0;i<config.count;i++)instance->values[i]=config.parameters[i].initial;
		return instance->componentVtbl->queryInterface (instance, iid, obj);
	}
	if (compare_iid (cid, factory->classes[1].cid))
	{
		AGainEditController* instance = (AGainEditController*)malloc (sizeof (AGainEditController));
		if(!instance)return Steinberg_kOutOfMemory;
        memset(instance,0,sizeof(*instance));
		instance->editControllerVtbl = &kAGainEditControllerVtbl.editController;
		instance->connectionPointVtbl = &kAGainEditControllerVtbl.connectionPoint;
		instance->editController2Vtbl = &kAGainEditControllerVtbl.editController2;
		instance->refCount = 0;
		for(U i=0;i<config.count;i++)instance->values[i]=config.parameters[i].initial;
		*obj = instance;
		return instance->editControllerVtbl->queryInterface (instance, iid, obj);
	}
	return Steinberg_kResultFalse;
}

/* methods defined in "Steinberg_IPluginFactory2": */
Steinberg_tresult SMTG_STDMETHODCALLTYPE AGainFactory_GetClassInfo2 (
    void* thisInterface, Steinberg_int32 index, struct Steinberg_PClassInfo2* info)
{
	if (index < 0 || index > 1 || info == 0)
	{
		return Steinberg_kInvalidArgument;
	}
	AGainFactory* factory = (AGainFactory*)thisInterface;
	memcpy (info, &factory->classes[index], sizeof (struct Steinberg_PClassInfo2));
	return Steinberg_kResultTrue;
}

static const struct AGainFactoryVtbl kAGainPluginFactoryVtbl = {
    {AGainFactory_QueryInterface, AGainFactory_AddRef, AGainFactory_Release,
     AGainFactory_GetFactoryInfo, AGainFactory_CountClasses, AGainFactory_GetClassInfo,
     AGainFactory_CreateInstance, AGainFactory_GetClassInfo2}};

#ifndef SMTG_EXPORT_SYMBOL
#if __APPLE__ || (defined(__gnu_linux__) && __gnu_linux__) || (defined(__linux__) && __linux__)
#define SMTG_EXPORT_SYMBOL __attribute__ ((visibility ("default")))
#elif defined(_WIN32)
#define SMTG_EXPORT_SYMBOL __declspec (dllexport)
#else
#error unknown platform
#endif // __APPLE__ ...
#endif // SMTG_EXPORT_SYMBOL

SMTG_EXPORT_SYMBOL Steinberg_IPluginFactory* SMTG_STDMETHODCALLTYPE GetPluginFactory ()
{
	static AGainFactory againFactory;
	static int32_t once = 1;
 if(!load_configuration())return NULL;
	if (once)
	{
		once = 0;

		againFactory.pluginFactoryVtbl = &kAGainPluginFactoryVtbl.pluginFactory;

		if(!load_configuration())return NULL; narrow(againFactory.factoryInfo.vendor,config.vendor,64);
		strcpy (againFactory.factoryInfo.email, "");
		strcpy (againFactory.factoryInfo.url, "");
		againFactory.factoryInfo.flags = 16;

		memcpy (againFactory.classes[0].cid, audioProcessorUID, sizeof (Steinberg_TUID));
		againFactory.classes[0].cardinality = Steinberg_PClassInfo_ClassCardinality_kManyInstances;
		strcpy (againFactory.classes[0].category, "Audio Module Class");
		narrow(againFactory.classes[0].name,config.title,64);
		againFactory.classes[0].classFlags = Steinberg_Vst_ComponentFlags_kDistributable;
		strcpy (againFactory.classes[0].subCategories, "Fx");
		narrow(againFactory.classes[0].vendor,config.vendor,64);
		strcpy (againFactory.classes[0].version, "1.0.0");
		strcpy (againFactory.classes[0].sdkVersion, "3.7.6");

		memcpy (againFactory.classes[1].cid, editControllerUID, sizeof (Steinberg_TUID));
		againFactory.classes[1].cardinality = Steinberg_PClassInfo_ClassCardinality_kManyInstances;
		strcpy (againFactory.classes[1].category, "Component Controller Class");
		narrow(againFactory.classes[1].name,config.title,64);
		againFactory.classes[1].classFlags = Steinberg_Vst_ComponentFlags_kDistributable;
		strcpy (againFactory.classes[1].subCategories, "Fx");
		narrow(againFactory.classes[1].vendor,config.vendor,64);
		strcpy (againFactory.classes[1].version, "1.0.0");
		strcpy (againFactory.classes[1].sdkVersion, "3.7.6");
	}

	return (Steinberg_IPluginFactory*)&againFactory;
}

/* Entry and Exit functions */
#if __APPLE__

SMTG_EXPORT_SYMBOL Steinberg_TBool bundleEntry (void* bundleRef)
{
	return 1;
}
SMTG_EXPORT_SYMBOL Steinberg_TBool bundleExit (void* bundleRef)
{
	return 1;
}

#elif defined(_WIN32)

SMTG_EXPORT_SYMBOL Steinberg_TBool InitDll ()
{
	return 1;
}

SMTG_EXPORT_SYMBOL Steinberg_TBool ExitDll ()
{
	return 1;
}

#elif (defined(__gnu_linux__) && __gnu_linux__) || (defined(__linux__) && __linux__)

SMTG_EXPORT_SYMBOL Steinberg_TBool ModuleEntry (void* sharedLibraryHandle)
{
	return 1;
}

SMTG_EXPORT_SYMBOL Steinberg_TBool ModuleExit (void)
{
	return 1;
}

#else
#error unknown platform
#endif // __APPLE__
