// SPDX-License-Identifier: GPL-2.0-or-later
// Precompiled mesh decoding only. All surface union, clipping and strokes are offline.
struct IllustratedArea {
 Mesh ground,outline,fringe,art; Buffers buffers; Json overlaps;std::string texture="forest-atlas.bbra";
 struct Sheet {Mesh floor,edges;Json surfaces;float meanY=0;};
 struct Crossing {Mesh mask,upper,lower,upperEdges,lowerEdges;std::vector<Sheet> sheets;int focus=-1;};
 std::vector<Crossing> crossings;
 std::vector<bool> lowerFocus;
};
std::shared_ptr<IllustratedArea> ReadIllustrated(Area& a){
 if(!a.manifest.at("files").contains("navigation.a3z"))return {};
 auto j=Blob(a,"navigation.a3z");
 if(j.at("schema")!=1)throw std::runtime_error("illustrated navigation schema");
 auto n=std::make_shared<IllustratedArea>();n->texture=j.value("art_texture",std::string("forest-atlas.bbra"));
 n->ground=ParseMesh(j["ground"],n->buffers);n->outline=ParseMesh(j["outline"],n->buffers);
 n->fringe=ParseMesh(j["fringe"],n->buffers);n->art=ParseMesh(j["art"],n->buffers);
 n->overlaps=j.value("overlaps",Json::array());
 for(auto& o:n->overlaps){IllustratedArea::Crossing c;
  c.mask=ParseMesh(o["mask_mesh"],n->buffers);c.upper=ParseMesh(o["upper_mesh"],n->buffers);c.lower=ParseMesh(o["lower_mesh"],n->buffers);
  c.upperEdges=ParseMesh(o["upper_edges"],n->buffers);c.lowerEdges=ParseMesh(o["lower_edges"],n->buffers);
  for(auto& sj:o.value("sheets",Json::array())){IllustratedArea::Sheet s;s.floor=ParseMesh(sj["mesh"],n->buffers);s.edges=ParseMesh(sj["edges"],n->buffers);s.surfaces=sj.at("surfacesXYZ");s.meanY=sj.at("mean_y");c.sheets.push_back(std::move(s));}
  n->crossings.push_back(std::move(c));n->lowerFocus.push_back(false);
 }
 return n;
}
float illustratedPlayerY=0;
bool PointInNavigation(const Json& triangles,float x,float z){
 for(const auto& t:triangles){float a=(t[2].get<float>()-t[0].get<float>())*(z-t[1].get<float>())-(t[3].get<float>()-t[1].get<float>())*(x-t[0].get<float>()),b=(t[4].get<float>()-t[2].get<float>())*(z-t[3].get<float>())-(t[5].get<float>()-t[3].get<float>())*(x-t[2].get<float>()),c=(t[0].get<float>()-t[4].get<float>())*(z-t[5].get<float>())-(t[1].get<float>()-t[5].get<float>())*(x-t[4].get<float>());if((a>=-.001f&&b>=-.001f&&c>=-.001f)||(a<=.001f&&b<=.001f&&c<=.001f))return true;}
 return false;
}
float SurfaceDistance(const Json& surfaces,float x,float y,float z){
 float best=1e9f;for(const auto& t:surfaces){float ax=t[0][0],ay=t[0][1],az=t[0][2],bx=t[1][0],by=t[1][1],bz=t[1][2],cx=t[2][0],cy=t[2][1],cz=t[2][2];float den=(bz-cz)*(ax-cx)+(cx-bx)*(az-cz);if(std::abs(den)<1e-8f)continue;float u=((bz-cz)*(x-cx)+(cx-bx)*(z-cz))/den,v=((cz-az)*(x-cx)+(ax-cx)*(z-cz))/den;if(u>=-.001f&&v>=-.001f&&u+v<=1.001f)best=std::min(best,std::abs(y-(u*ay+v*by+(1-u-v)*cy)));}return best;
}
bool LowerPassage(size_t k){
 if(!area||!area->illustrated)return false;auto& n=*area->illustrated;const char* mode=std::getenv("BB_ATLAS_PASSAGE");
 if(mode&&std::string(mode)=="lower")return true;if(mode&&std::string(mode)=="upper")return false;
 const auto& o=n.overlaps[k];
 // Only actual overlap windows select a floor; slopes elsewhere remain whole.
 if(PointInNavigation(o["overlap_geometry"]["triangles"],last_x,last_z)){
  float hi=SurfaceDistance(o["upper_surfaces"],last_x,illustratedPlayerY,last_z),lo=SurfaceDistance(o["lower_surfaces"],last_x,illustratedPlayerY,last_z);
  if(lo+.65f<hi&&lo<1.7f)n.lowerFocus[k]=true;else if(hi+.65f<lo&&hi<1.7f)n.lowerFocus[k]=false;
 }return n.lowerFocus[k];
}
int PassageSheet(size_t k){
 auto& crossing=area->illustrated->crossings[k];if(crossing.sheets.empty())return -1;
 const char* mode=std::getenv("BB_ATLAS_PASSAGE");int selected=0;
 if(mode&&(std::string(mode)=="upper"||std::string(mode)=="lower")){
  bool lower=std::string(mode)=="lower";for(size_t i=1;i<crossing.sheets.size();++i)if(lower?crossing.sheets[i].meanY<crossing.sheets[selected].meanY:crossing.sheets[i].meanY>crossing.sheets[selected].meanY)selected=int(i);return selected;
 }
 float best=1e9f;
 for(size_t i=0;i<crossing.sheets.size();++i){float d=SurfaceDistance(crossing.sheets[i].surfaces,last_x,illustratedPlayerY,last_z);if(d<best){best=d;selected=int(i);}}
 if(crossing.focus<0){crossing.focus=0;for(size_t i=1;i<crossing.sheets.size();++i)if(crossing.sheets[i].meanY>crossing.sheets[crossing.focus].meanY)crossing.focus=int(i);}
 if(best<1.7f){float previous=SurfaceDistance(crossing.sheets[crossing.focus].surfaces,last_x,illustratedPlayerY,last_z);if(selected==crossing.focus||best+.65f<previous)crossing.focus=selected;}
 return crossing.focus;
}
