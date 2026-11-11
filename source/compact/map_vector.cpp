// SPDX-License-Identifier: GPL-2.0-or-later
// Compiled vector renderer. Only bounded file decoding runs on one worker.
// World geometry and stroke extrusion are prepared offline and uploaded once.
#include "bbport_map_static.h"
#include "bbport_map_features.h"
#include "imgui_internal.h"
#include "backends/imgui_impl_vulkan.h"
#include "core.h"
#include <future>
#include <memory>
#include <cstring>
#include <chrono>
#include <cstdlib>
extern "C" bool BbAtlasVectorBackend(VkDevice*,VkPhysicalDevice*,VkDescriptorSet*,VkPipelineLayout*,VkPipeline*);
namespace BbMapStatic {namespace {
using namespace Atlas2;using Clock=std::chrono::steady_clock;
constexpr size_t Limit=256*1024*1024;
struct Group {uint32_t first,count;std::vector<int> required;};
struct Mesh {uint32_t first=0,count=0,vertex=0;std::vector<Group> groups;};
struct Buffers {std::vector<unsigned char> vertices,indices;};
struct Layer {float anchor,low,high;Mesh floors,outlines,walls,interiors;};
struct Hatch {Mesh cut,interior;};
struct IllustratedArea;
struct Area {std::shared_ptr<IllustratedArea> illustrated;std::string region;fs::path root;Json manifest;Grid grid;Buffers buffers;std::vector<Layer> layers;std::array<float,4> bounds;int primary;uint64_t serial=0;};
struct Hatches {std::string region;int lod=-1;uint64_t serial=0;Buffers buffers;std::vector<Hatch> layers;};
struct GpuBuffer {VkBuffer vertices{},indices{};VkDeviceMemory vm{},im{};uint64_t serial=0;size_t bytes=0;};
std::shared_ptr<Area> area;std::shared_ptr<Hatches> hatches;
std::future<std::shared_ptr<Area>> area_job;std::future<std::shared_ptr<Hatches>> hatch_job;
std::string requested,area_target,failed,error;int hatch_requested=-1,previous=-1,manual=-1,mode=0,last_lod=5;
bool prior_valid=false;float last_x=0,last_z=0;uint64_t serial=0,requests=0,failures=0,uploads=0;double submit_ms=0,callback_ms=0;
VkDevice device{};VkPhysicalDevice physical{};VkDescriptorSet sampler{};VkPipeline pipeline{};VkPipelineLayout layout{};GpuBuffer base_gpu,hatch_gpu,illustrated_gpu;
std::unique_ptr<ImTextureData> parchment,white,forest,urban;
int draw_calls=0,active_layer=-1;struct Frame {ImVec2 center,extent;float x,z,zoom,scale,opacity;bool shading,fog;std::vector<bool> flags;} frame;
bool Busy(){return area_job.valid()||hatch_job.valid();}
template<class T>bool Ready(std::future<T>& job){return job.valid()&&job.wait_for(std::chrono::seconds(0))==std::future_status::ready;}
std::vector<unsigned char> Inflate(fs::path p,const std::string& hash){auto b=Read(p,Limit);if(b.size()<8||std::memcmp(b.data(),"A3Z1",4)||Hash(b)!=hash)throw std::runtime_error("compiled map integrity");auto size=U32(b.data()+4);if(size>Limit)throw std::runtime_error("compiled map size");std::vector<unsigned char> out(size);uLongf n=size;uLong used=uLong(b.size()-8);if(uncompress2(out.data(),&n,b.data()+8,&used)!=Z_OK||n!=size||used!=b.size()-8)throw std::runtime_error("compiled map decode");return out;}
Json Blob(const Area& a,const std::string& name){if(name.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789-.")!=std::string::npos)throw std::runtime_error("compiled path");return Json::from_msgpack(Inflate(a.root/name,a.manifest.at("files").at(name)));}
Mesh ParseMesh(Json& j,Buffers& out){Mesh mesh;const auto& v=j.at("vertices").get_binary();const auto& i=j.at("indices").get_binary();if(v.size()%20||i.size()%4||out.vertices.size()+v.size()>Limit||out.indices.size()+i.size()>Limit)throw std::runtime_error("compiled mesh bounds");mesh.vertex=uint32_t(out.vertices.size()/20);mesh.first=uint32_t(out.indices.size()/4);mesh.count=uint32_t(i.size()/4);if(mesh.count%3)throw std::runtime_error("compiled triangle count");
 for(size_t k=0;k<i.size();k+=4)if(U32(i.data()+k)>=v.size()/20)throw std::runtime_error("compiled vertex index");
 uint32_t end=0;for(const auto& g:j.at("groups")){Group group{g.at(0),g.at(1),g.at(2).get<std::vector<int>>()};if(group.first!=end||group.count>mesh.count-end||group.required.size()>256)throw std::runtime_error("compiled draw range");for(int r:group.required)if(r< -1||r>255)throw std::runtime_error("compiled reveal index");end+=group.count;mesh.groups.push_back(std::move(group));}if(end!=mesh.count)throw std::runtime_error("compiled mesh coverage");out.vertices.insert(out.vertices.end(),v.begin(),v.end());out.indices.insert(out.indices.end(),i.begin(),i.end());return mesh;}
#include "illustrated_draw.h"
std::shared_ptr<Area> ReadArea(std::string region,uint64_t id){const char* dir=std::getenv("BB_ATLAS2_DIR"),*hash=std::getenv("BB_ATLAS2_INDEX_SHA256");if(!dir||!hash)throw std::runtime_error("compiled map configuration");auto bytes=Read(fs::path(dir)/"atlas2-index.json",1024*1024);if(Hash(bytes)!=hash)throw std::runtime_error("compiled index integrity");auto index=Json::parse(bytes);if(index.at("schema")!=1||index.at("format")!="compiled-vector-v1"||index.at("areas").size()!=16)throw std::runtime_error("compiled index format");Json entry;for(const auto& e:index.at("areas"))if(e.at("region_id")==region)entry=e;if(entry.is_null())throw std::runtime_error("compiled region missing");std::string label=entry.at("area");if(label.size()!=6||label.rfind("Area",0)||label.find_first_not_of("0123456789",4)!=std::string::npos)throw std::runtime_error("compiled area name");auto result=std::make_shared<Area>();result->region=region;result->serial=id;result->root=fs::path(dir)/label;bytes=Read(result->root/"manifest.json",1024*1024);if(Hash(bytes)!=entry.at("manifest_sha256").get<std::string>())throw std::runtime_error("compiled manifest integrity");result->manifest=Json::parse(bytes);if(result->manifest.at("schema")!=4||result->manifest.at("region_id")!=region)throw std::runtime_error("compiled manifest schema");result->bounds=result->manifest.at("bounds").get<std::array<float,4>>();for(float v:result->bounds)if(!std::isfinite(v))throw std::runtime_error("compiled bounds");result->primary=result->manifest.at("primary");result->grid.FromJson(Blob(*result,"grid.a3z"));auto base=Blob(*result,"base.a3z");if(base.at("schema")!=1||base.at("layers").size()!=result->grid.anchors.size())throw std::runtime_error("compiled layer identity");for(auto& l:base["layers"]){Layer layer{l.at("anchor"),l.at("low"),l.at("high")};layer.floors=ParseMesh(l["floors"],result->buffers);layer.outlines=ParseMesh(l["outlines"],result->buffers);layer.walls=ParseMesh(l["walls"],result->buffers);layer.interiors=ParseMesh(l["interiors"],result->buffers);result->layers.push_back(std::move(layer));}if(result->primary<0||result->primary>=int(result->layers.size()))throw std::runtime_error("compiled primary floor");result->illustrated=ReadIllustrated(*result);return result;}
std::shared_ptr<Hatches> ReadHatches(std::shared_ptr<Area> source,int lod,uint64_t id){auto j=Blob(*source,"hatch-"+std::to_string(lod)+".a3z");auto result=std::make_shared<Hatches>();result->region=source->region;result->lod=lod;result->serial=id;if(j.at("schema")!=1||j.at("layers").size()!=source->layers.size())throw std::runtime_error("compiled hatch identity");for(auto& l:j["layers"]){Hatch h;h.cut=ParseMesh(l["cut"],result->buffers);h.interior=ParseMesh(l["interior"],result->buffers);result->layers.push_back(std::move(h));}return result;}
void Pump(){if(Ready(area_job)){try{auto next=area_job.get();if(next->region==requested){area=std::move(next);hatches.reset();previous=-1;prior_valid=false;error.clear();}}catch(const std::exception& e){failed=area_target;if(failed==requested){error=e.what();++failures;}}}
 if(Ready(hatch_job)){try{auto next=hatch_job.get();if(area&&next->region==area->region){hatches=std::move(next);error.clear();}}catch(const std::exception& e){error=e.what();++failures;}hatch_requested=-1;}}
void RequestHatches(int lod){Pump();if(!area||area->region!=requested||hatches&&hatches->region==area->region&&hatches->lod==lod||Busy())return;auto source=area;uint64_t id=++serial;hatch_requested=lod;++requests;hatch_job=std::async(std::launch::async,[source,lod,id](){return ReadHatches(source,lod,id);});}
void Check(VkResult value){if(value!=VK_SUCCESS)throw std::runtime_error("compiled map GPU allocation "+std::to_string(value));}
uint32_t Memory(uint32_t bits){VkPhysicalDeviceMemoryProperties props;vkGetPhysicalDeviceMemoryProperties(physical,&props);for(uint32_t i=0;i<props.memoryTypeCount;++i)if((bits&(1u<<i))&&(props.memoryTypes[i].propertyFlags&(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))==(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))return i;throw std::runtime_error("compiled map GPU memory");}
void Free(GpuBuffer& b){if(!device)return;if(b.vertices)vkDestroyBuffer(device,b.vertices,nullptr);if(b.indices)vkDestroyBuffer(device,b.indices,nullptr);if(b.vm)vkFreeMemory(device,b.vm,nullptr);if(b.im)vkFreeMemory(device,b.im,nullptr);b={};}
void UploadOne(VkBuffer& buffer,VkDeviceMemory& memory,const std::vector<unsigned char>& bytes,VkBufferUsageFlags usage){if(bytes.empty())return;VkBufferCreateInfo ci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};ci.size=bytes.size();ci.usage=usage;Check(vkCreateBuffer(device,&ci,nullptr,&buffer));VkMemoryRequirements req;vkGetBufferMemoryRequirements(device,buffer,&req);VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};ai.allocationSize=req.size;ai.memoryTypeIndex=Memory(req.memoryTypeBits);Check(vkAllocateMemory(device,&ai,nullptr,&memory));Check(vkBindBufferMemory(device,buffer,memory,0));void* data;Check(vkMapMemory(device,memory,0,bytes.size(),0,&data));std::memcpy(data,bytes.data(),bytes.size());vkUnmapMemory(device,memory);}
void Upload(GpuBuffer& target,const Buffers& source,uint64_t id){if(target.serial==id)return;GpuBuffer next;try{UploadOne(next.vertices,next.vm,source.vertices,VK_BUFFER_USAGE_VERTEX_BUFFER_BIT);UploadOne(next.indices,next.im,source.indices,VK_BUFFER_USAGE_INDEX_BUFFER_BIT);next.serial=id;next.bytes=source.vertices.size()+source.indices.size();if(target.vertices||target.indices)Check(vkDeviceWaitIdle(device));Free(target);target=next;++uploads;}catch(...){Free(next);throw;}}
void Textures(){if(white)return;auto make=[](int w,int h){auto t=std::make_unique<ImTextureData>();t->Create(ImTextureFormat_RGBA32,w,h);t->UseColors=true;static int unique=4000000;t->UniqueID=unique++;return t;};auto art=std::getenv("BB_MAP_ART_DIR");if(!art)throw std::runtime_error("compiled map art directory");auto b=Read(fs::path(art)/"parchment.bbra",64*1024*1024+12);if(b.size()<12||std::memcmp(b.data(),"BBRA",4))throw std::runtime_error("compiled map parchment");int w=U32(b.data()+4),h=U32(b.data()+8);if(w<1||h<1||w>4096||h>4096||b.size()!=12+size_t(w)*h*4)throw std::runtime_error("compiled map texture bounds");auto p=make(w,h);std::memcpy(p->GetPixels(),b.data()+12,b.size()-12);auto blank=make(2,2);std::memset(blank->GetPixels(),255,16);ImGui::RegisterUserTexture(p.get());ImGui::RegisterUserTexture(blank.get());parchment=std::move(p);white=std::move(blank);
 for(auto item:{std::pair{"forest-atlas.bbra",&forest},std::pair{"urban-atlas.bbra",&urban}}){
  auto data=Read(fs::path(art)/item.first,64*1024*1024+12);if(data.size()<12||std::memcmp(data.data(),"BBRA",4))throw std::runtime_error("illustrated texture");int w=U32(data.data()+4),h=U32(data.data()+8);if(w<1||h<1||w>4096||h>4096||data.size()!=12+size_t(w)*h*4)throw std::runtime_error("illustrated texture bounds");auto t=make(w,h);std::memcpy(t->GetPixels(),data.data()+12,data.size()-12);ImGui::RegisterUserTexture(t.get());*item.second=std::move(t);
 }
}
struct Constants {float view[4],data[4],paint[4],params[4];};
bool SkipArt(){static const bool v=[](){const char*e=std::getenv("BB_ATLAS2_SKIP_ART");return e&&e[0]=='1'; }();return v;} bool SkipGround(){static const bool v=[](){const char*e=std::getenv("BB_ATLAS2_SKIP_GROUND");return e&&e[0]=='1'; }();return v;} bool Allowed(const Group& group){if(!frame.fog)return true;for(int r:group.required)if(r<0||r>=int(frame.flags.size())||!frame.flags[r])return false;return true;}
void RenderMesh(VkCommandBuffer cmd,const Mesh& mesh,const GpuBuffer& buffer,Constants constants,int kind,std::array<float,4> paint,float width=0,int wear=0){if(!mesh.count||!buffer.vertices)return;constants.data[3]=float(kind);std::copy(paint.begin(),paint.end(),constants.paint);constants.params[2]=width;constants.params[3]=float(wear);auto texture=kind==4?forest->GetTexID():kind==5?urban->GetTexID():(kind==1||kind==3)?parchment->GetTexID():white->GetTexID();VkDescriptorSet descriptor=(VkDescriptorSet)(uintptr_t)texture;vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_GRAPHICS,layout,0,1,&descriptor,0,nullptr);VkDeviceSize zero=0;vkCmdBindVertexBuffers(cmd,0,1,&buffer.vertices,&zero);vkCmdBindIndexBuffer(cmd,buffer.indices,0,VK_INDEX_TYPE_UINT32);vkCmdPushConstants(cmd,layout,VK_SHADER_STAGE_VERTEX_BIT,0,sizeof(constants),&constants);if(!frame.fog){vkCmdDrawIndexed(cmd,mesh.count,1,mesh.first,int32_t(mesh.vertex),0);++draw_calls;}else {uint32_t first=0,count=0;auto flush=[&](){if(count){vkCmdDrawIndexed(cmd,count,1,mesh.first+first,int32_t(mesh.vertex),0);++draw_calls;count=0;}};for(const auto& g:mesh.groups){if(!Allowed(g)){flush();continue;}if(count&&first+count!=g.first)flush();if(!count)first=g.first;count+=g.count;}flush();}}
void Callback(const ImDrawList*,const ImDrawCmd* command){auto start=Clock::now();try{
 if(!area||active_layer<0||active_layer>=int(area->layers.size())||!parchment||parchment->Status!=ImTextureStatus_OK||white->Status!=ImTextureStatus_OK)return;
 if(!BbAtlasVectorBackend(&device,&physical,&sampler,&layout,&pipeline))throw std::runtime_error("compiled vector pipeline");auto* state=static_cast<ImGui_ImplVulkan_RenderState*>(ImGui::GetPlatformIO().Renderer_RenderState);if(!state)return;
 if(!area->illustrated)Upload(base_gpu,area->buffers,area->serial);if(hatches&&hatches->region==area->region)Upload(hatch_gpu,hatches->buffers,hatches->serial);
 auto* dd=ImGui::GetDrawData();auto pos=dd->DisplayPos,size=dd->DisplaySize,scale=dd->FramebufferScale;if(size.x<=0||size.y<=0)return;
 auto clip=command->ClipRect;float x0=std::clamp((clip.x-pos.x)*scale.x,0.f,size.x*scale.x),y0=std::clamp((clip.y-pos.y)*scale.y,0.f,size.y*scale.y),x1=std::clamp((clip.z-pos.x)*scale.x,0.f,size.x*scale.x),y1=std::clamp((clip.w-pos.y)*scale.y,0.f,size.y*scale.y);if(x1<=x0||y1<=y0)return;VkRect2D scissor{{int32_t(x0),int32_t(y0)},{uint32_t(x1-x0),uint32_t(y1-y0)}};vkCmdSetScissor(state->CommandBuffer,0,1,&scissor);vkCmdBindPipeline(state->CommandBuffer,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);vkCmdBindDescriptorSets(state->CommandBuffer,VK_PIPELINE_BIND_POINT_GRAPHICS,layout,1,1,&sampler,0,nullptr);
 Constants c{{2*frame.zoom/size.x,2*frame.zoom/size.y,2*(frame.center.x-frame.x*frame.zoom-pos.x)/size.x-1,2*(frame.center.y+frame.z*frame.zoom-pos.y)/size.y-1},{(area->bounds[0]+area->bounds[2])*.5f,(area->bounds[1]+area->bounds[3])*.5f,std::max(area->bounds[2]-area->bounds[0],area->bounds[3]-area->bounds[1]),0},{},{2/size.x,2/size.y,0,0}};
 if(area->illustrated){
  auto& n=*area->illustrated;Upload(illustrated_gpu,n.buffers,area->serial);auto cmd=state->CommandBuffer;draw_calls=0;
  // The old world-width green fringe read as a heavy border at close zoom.
  // Keep the source footprint and use a restrained screen-width warm ink edge.
  if(!SkipGround())RenderMesh(cmd,n.ground,illustrated_gpu,c,3,{.77f,.68f,.48f,1});
  RenderMesh(cmd,n.outline,illustrated_gpu,c,2,{.30f,.25f,.18f,.92f},std::clamp(.55f*frame.scale,.55f,1.65f));
  if(!SkipArt()&&forest&&urban&&forest->Status==ImTextureStatus_OK&&urban->Status==ImTextureStatus_OK)RenderMesh(cmd,n.art,illustrated_gpu,c,n.texture=="urban-atlas.bbra"?5:4,{.88f,.90f,.85f,.95f});
  for(size_t k=0;k<n.crossings.size();++k){const auto& p=n.crossings[k];bool lower=LowerPassage(k);
   auto any=[&](const Mesh& m){if(!frame.fog)return m.count>0;for(const auto& g:m.groups)if(Allowed(g))return true;return false;};
   int sheet=PassageSheet(k);
   if(sheet>=0){
    if(!any(p.sheets[sheet].floor)){sheet=-1;for(size_t i=0;i<p.sheets.size();++i)if(any(p.sheets[i].floor)){sheet=int(i);break;}}
    if(sheet>=0){RenderMesh(cmd,p.sheets[sheet].edges,illustrated_gpu,c,2,{.23f,.20f,.16f,.94f},std::clamp(frame.scale,.75f,3.f));RenderMesh(cmd,p.sheets[sheet].floor,illustrated_gpu,c,3,{.80f,.71f,.51f,1});continue;}
   }
   if(!any(lower?p.lower:p.upper)&&any(lower?p.upper:p.lower))lower=!lower;
   // The selected passage occludes underlying geometry only at its real footprint.
   // A connected overlap region can contain unrelated routes: never erase it wholesale.
   RenderMesh(cmd,lower?p.lowerEdges:p.upperEdges,illustrated_gpu,c,2,{.23f,.20f,.16f,.94f},std::clamp(frame.scale,.75f,3.f));
   RenderMesh(cmd,lower?p.lower:p.upper,illustrated_gpu,c,3,lower?std::array<float,4>{.64f,.58f,.46f,1}:std::array<float,4>{.84f,.73f,.50f,1});
  }
  callback_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();return;
 }
 auto cmd=state->CommandBuffer;const auto& active=area->layers[active_layer];float low=active.anchor,high=low;for(const auto& l:area->layers)if(std::abs(l.anchor-active.anchor)<=6){low=std::min(low,l.low);high=std::max(high,l.high);}draw_calls=0;
 auto colour=[&](int r,int g,int b,int a){return std::array<float,4>{r/255.f,g/255.f,b/255.f,a/255.f*frame.opacity};};
 for(int pass=0;pass<2;++pass)for(size_t li=0;li<area->layers.size();++li)if((int(li)==active_layer)==(pass==1))RenderMesh(cmd,area->layers[li].interiors,base_gpu,c,0,pass?colour(53,48,39,255):colour(44,41,34,255));
 const bool hatched=hatches&&hatches->region==area->region&&hatch_gpu.serial==hatches->serial;const float thin=std::clamp(.72f*frame.scale,.6f,1.3f);
 if(hatched)for(size_t li=0;li<hatches->layers.size();++li)RenderMesh(cmd,hatches->layers[li].interior,hatch_gpu,c,2,colour(135,119,90,0),thin,int(li)==active_layer?1:2);
 for(size_t li=0;li<area->layers.size();++li)if(int(li)!=active_layer){const auto& l=area->layers[li];bool near=std::abs(l.anchor-active.anchor)<=6;RenderMesh(cmd,l.floors,base_gpu,c,1,{low,high,(near?38.f:27.f)/255*frame.opacity,frame.shading?1.f:0.f});RenderMesh(cmd,l.outlines,base_gpu,c,2,colour(213,203,177,near?62:49),.7f*frame.scale);}
 if(hatched)RenderMesh(cmd,hatches->layers[active_layer].cut,hatch_gpu,c,2,colour(166,160,143,0),thin,1);
 RenderMesh(cmd,active.floors,base_gpu,c,1,{low,high,frame.opacity,frame.shading?1.f:0.f});RenderMesh(cmd,active.outlines,base_gpu,c,2,colour(204,193,163,220),.85f*frame.scale);RenderMesh(cmd,active.walls,base_gpu,c,2,colour(15,18,19,255),std::clamp(frame.zoom*.13f,2.5f*frame.scale,5.f*frame.scale));
 }catch(const std::exception& e){error=e.what();++failures;}callback_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();}
} // anonymous

bool Illustrated(){return area&&bool(area->illustrated);}
bool PassageMarkerVisible(float x,float y,float z){
 if(!area||!area->illustrated)return true;auto& n=*area->illustrated;
 for(size_t k=0;k<n.overlaps.size();++k){const auto& o=n.overlaps[k];if(!PointInNavigation(o["overlap_geometry"]["triangles"],x,z))continue;
  int sheet=PassageSheet(k);float chosen=1e9f,other=1e9f;
  if(sheet>=0){auto& crossing=n.crossings[k];chosen=SurfaceDistance(crossing.sheets[sheet].surfaces,x,y,z);for(size_t i=0;i<crossing.sheets.size();++i)if(int(i)!=sheet)other=std::min(other,SurfaceDistance(crossing.sheets[i].surfaces,x,y,z));}
  else{bool lower=LowerPassage(k);chosen=SurfaceDistance(o[lower?"lower_surfaces":"upper_surfaces"],x,y,z);other=SurfaceDistance(o[lower?"upper_surfaces":"lower_surfaces"],x,y,z);}
  if(chosen<1e8f&&chosen>2.f&&other+.35f<chosen)return false;
 }return true;
}

bool Enabled(){const char* e=std::getenv("BB_ATLAS2_ENABLED");return e&&std::string(e)=="1";}
bool Load(const std::string& region){if(!Enabled()||region.empty())return false;Pump();if(requested!=region){requested=region;previous=-1;prior_valid=false;manual=-1;}if(area&&area->region==region)return true;if(failed==region||Busy())return false;++requests;area_target=region;uint64_t id=++serial;area_job=std::async(std::launch::async,[region,id](){return ReadArea(region,id);});return false;}
int Select(const std::string& region,float x,float y,float z,bool valid,bool continuity){illustratedPlayerY=y;if(!valid||!Load(region)){prior_valid=false;previous=-1;return -1;}bool keep=continuity&&prior_valid&&std::hypot(x-last_x,z-last_z)<20;int selected=area->grid.Select(x,y,z,keep?previous:-1,keep?.35f:0.f,manual);if(selected<0&&area->illustrated){float best=1e9f;for(size_t i=0;i<area->layers.size();++i){float d=std::abs(area->layers[i].anchor-y);if(d<best){best=d;selected=int(i);}}}if(continuity){previous=selected;last_x=x;last_z=z;prior_valid=selected>=0;}return selected;}
int StrictLayer(const std::string& region,float x,float y,float z,bool valid){return valid&&Load(region)?area->grid.Select(x,y,z):-1;}
int Primary(const std::string& region){return Load(region)?area->primary:-1;}
int ManualLayer(){return manual;}int Mode(){return mode;}
void Command(const std::string& c){if(c=="atlas2-floor-auto"){manual=-1;previous=-1;prior_valid=false;}if(c.rfind("atlas2-floor ",0)==0)try{int v=std::stoi(c.substr(13));if(area&&v>=0&&v<int(area->layers.size()))manual=v;}catch(...){}/* Raster/reference fallback is deliberately absent from this runtime. */}
Json ProjectionMetrics(float,float,float){return {{"roundtrip_world_delta",0},{"roundtrip_pixel_delta",0},{"kind","direct world coordinates on GPU"}};}
void Draw(ImDrawList* draw,const std::string& region,int layer,ImVec2 center,ImVec2 extent,float x,float z,float zoom,float opacity,bool shading,float scale){auto start=Clock::now();if(!std::isfinite(x)||!std::isfinite(z)||!std::isfinite(zoom)||zoom<=0||!std::isfinite(scale)||scale<=0||!Load(region)||layer<0||layer>=int(area->layers.size())){draw->AddText(center,IM_COL32(223,214,187,255),error.empty()?"Loading map...":"Map data unavailable. See the launcher log.");return;}
 try{Textures();last_lod=std::clamp(int(std::lround(std::log(5.5f*1.41421356237f*scale/std::max(.0001f,zoom*.125f))/std::log(1.5f))),2,17);if(!area->illustrated)RequestHatches(last_lod);frame={center,extent,x,z,zoom,scale,std::clamp(opacity,0.f,1.f),shading,BbMapFeatures::FogEnabled(),BbMapFeatures::StaticRegionVisibility(region)};active_layer=layer;draw->AddCallback(Callback,nullptr);draw->AddCallback(ImGui::GetPlatformIO().DrawCallback_ResetRenderState,nullptr);}catch(const std::exception& e){error=e.what();++failures;}submit_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();}
Json Stats(){return {{"schema",2},{"format","compiled-vector-v1"},{"mode",0},{"area_loaded",area&&area->region==requested},{"region_id",requested},{"layer",previous},{"draw_layer",active_layer},{"lod",last_lod},{"hatch_lod",area&&area->illustrated?last_lod:(hatches?hatches->lod:-1)},{"loader_jobs",int(area_job.valid())+int(hatch_job.valid())},{"loader_worker_limit",1},{"loader_requests",requests},{"gpu_buffer_bytes",base_gpu.bytes+hatch_gpu.bytes+illustrated_gpu.bytes},{"gpu_upload_batches_total",uploads},{"draw_calls",draw_calls},{"submit_ms",submit_ms},{"callback_ms",callback_ms},{"integrity_failures",failures},{"local_candidates",area?area->grid.last_candidates:0},{"illustrated",area&&bool(area->illustrated)},{"overlap_count",area&&area->illustrated?area->illustrated->crossings.size():0},{"per_frame_tessellation",false},{"collision_extraction",false},{"error",error}};}
void ReleaseGpu(){if(device){vkDeviceWaitIdle(device);Free(illustrated_gpu);Free(base_gpu);Free(hatch_gpu);}device={};physical={};pipeline={};layout={};sampler={};}
void Shutdown(){if(area_job.valid())try{area_job.get();}catch(...){}if(hatch_job.valid())try{hatch_job.get();}catch(...){}ReleaseGpu();for(auto* t:{&parchment,&white,&forest,&urban})if(*t&&(*t)->GetTexID()==ImTextureID_Invalid&&!(*t)->BackendUserData){ImGui::UnregisterUserTexture(t->get());t->reset();}area.reset();hatches.reset();requested.clear();failed.clear();previous=-1;prior_valid=false;}
} // namespace
void BbAtlasVectorReleaseGpu(){BbMapStatic::ReleaseGpu();}
