// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "core.h"
#include "../native/gpu/shim/bbport_atlas_interiors.h"
#include <set>

namespace Atlas2Parity {
using namespace Atlas2;
inline std::array<int,4> HeightTint(float y,float low,float high,int alpha,bool shaded){
    const float t=shaded?std::clamp((y-low)/std::max(.01f,high-low),0.f,1.f):.72f;
    const int q=int(118+120*t);return {q+4,q+2,q,alpha};
}
inline float WallWidth(float zoom,float scale){return std::clamp(zoom*.13f,2.5f*scale,5.f*scale);}
inline float OutlineWidth(float scale){return .85f*scale;}
inline std::vector<int> Requirements(const Json& feature,const std::vector<std::array<float,3>>& points){
    std::set<int> result;for(auto p:points){int id=Region(feature,p[0],p[1],p[2]);if(id!=-2)result.insert(id);}return {result.begin(),result.end()};
}
inline std::vector<int> BoxRequirements(const Json& feature,float x0,float z0,float x1,float z1,float y){
    return Requirements(feature,{{x0,y,z0},{x1,y,z1},{(x0+x1)*.5f,y,(z0+z1)*.5f}});
}
inline bool Visible(const std::vector<int>& required,int mask){
    if(mask<0)return true;for(int id:required)if(id<0||!(mask&(1<<id)))return false;return true;
}
struct Texture {
    int width=0,height=0;std::vector<unsigned char> pixels;
    explicit Texture(const fs::path& path){auto b=Read(path,64*1024*1024+12);if(b.size()<12||std::string((char*)b.data(),4)!="BBRA")throw std::runtime_error("parchment format");width=U32(b.data()+4);height=U32(b.data()+8);if(width<1||height<1||width>4096||height>4096||b.size()!=12+size_t(width)*height*4)throw std::runtime_error("parchment bounds");pixels.assign(b.begin()+12,b.end());}
    std::array<float,4> Sample(float u,float v)const{
        float x=std::clamp(u*width-.5f,0.f,float(width-1)),y=std::clamp(v*height-.5f,0.f,float(height-1));int x0=int(x),y0=int(y),x1=std::min(width-1,x0+1),y1=std::min(height-1,y0+1);float ax=x-x0,ay=y-y0;std::array<float,4> c{};
        for(int k=0;k<4;++k)c[k]=((1-ax)*pixels[(y0*width+x0)*4+k]+ax*pixels[(y0*width+x1)*4+k])*(1-ay)+((1-ax)*pixels[(y1*width+x0)*4+k]+ax*pixels[(y1*width+x1)*4+k])*ay;return c;
    }
};
struct Primitive {
    std::array<float,6> v{};std::array<std::array<int,4>,3> color{};std::vector<int> required;
    bool textured=false,stroke=false;float width=0;
};
struct Raster {
    Transform transform;int level=0,tx=0,ty=0;float material_x=0,material_z=0,material_span=1;const Texture* texture=nullptr;
    std::vector<unsigned char> pixels=std::vector<unsigned char>(TileBytes);
    void Blend(int x,int y,std::array<float,4> c){size_t at=(y*Dimension+x)*4;float sa=c[3]/255,da=pixels[at+3]/255.f,oa=sa+da*(1-sa);if(oa<=0)return;for(int k=0;k<3;++k)pixels[at+k]=uint8_t(std::clamp((c[k]*sa+pixels[at+k]*da*(1-sa))/oa,0.f,255.f)+.5f);pixels[at+3]=uint8_t(std::clamp(oa*255,0.f,255.f)+.5f);}
    void Draw(const Primitive& p){
        double factor=std::ldexp(1.,-level),density=transform.ppu*factor;std::array<double,6> v;
        for(int k=0;k<3;++k){auto q=transform.Image(p.v[k*2],p.v[k*2+1]);v[k*2]=q[0]*factor-tx*Tile+Gutter;v[k*2+1]=q[1]*factor-ty*Tile+Gutter;}
        if(p.stroke){
            double dx=v[2]-v[0],dy=v[3]-v[1],length2=dx*dx+dy*dy;if(length2<1e-12)return;double half=p.width*density*.5;
            int x0=std::max(0,int(std::floor(std::min(v[0],v[2])-half-1))),x1=std::min(Dimension-1,int(std::ceil(std::max(v[0],v[2])+half+1))),y0=std::max(0,int(std::floor(std::min(v[1],v[3])-half-1))),y1=std::min(Dimension-1,int(std::ceil(std::max(v[1],v[3])+half+1)));
            for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){double along=((x+.5-v[0])*dx+(y+.5-v[1])*dy)/length2;if(along<0||along>1)continue;double d=std::hypot(x+.5-(v[0]+along*dx),y+.5-(v[1]+along*dy));float coverage=float(std::clamp(half+.5-d,0.,1.));if(coverage<=0)continue;Blend(x,y,{float(p.color[0][0]),float(p.color[0][1]),float(p.color[0][2]),p.color[0][3]*coverage});}return;
        }
        double d=(v[3]-v[5])*(v[0]-v[4])+(v[4]-v[2])*(v[1]-v[5]);if(std::abs(d)<1e-12)return;
        auto top_left=[&](int a,int b){double dx=v[b*2]-v[a*2],dy=v[b*2+1]-v[a*2+1];if(d<0){dx=-dx;dy=-dy;}return dy<0||(dy==0&&dx>0);};
        int x0=std::max(0,int(std::floor(std::min({v[0],v[2],v[4]}))));
        int x1=std::min(Dimension-1,int(std::ceil(std::max({v[0],v[2],v[4]}))));
        int y0=std::max(0,int(std::floor(std::min({v[1],v[3],v[5]}))));
        int y1=std::min(Dimension-1,int(std::ceil(std::max({v[1],v[3],v[5]}))));
        for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){double a=((v[3]-v[5])*(x+.5-v[4])+(v[4]-v[2])*(y+.5-v[5]))/d,b=((v[5]-v[1])*(x+.5-v[4])+(v[0]-v[4])*(y+.5-v[5]))/d,c=1-a-b;if(a<0||b<0||c<0||a==0&&!top_left(1,2)||b==0&&!top_left(2,0)||c==0&&!top_left(0,1))continue;std::array<float,4> color{};for(int k=0;k<4;++k)color[k]=float(a*p.color[0][k]+b*p.color[1][k]+c*p.color[2][k]);
            if(p.textured){auto world=transform.World((x+.5+tx*Tile-Gutter)/factor,(y+.5+ty*Tile-Gutter)/factor);auto tex=texture->Sample(std::clamp(.5f+(float(world[0])-material_x)/material_span,0.f,1.f),std::clamp(.5f+(float(world[1])-material_z)/material_span,0.f,1.f));for(int k=0;k<4;++k)color[k]*=tex[k]/255.f;}Blend(x,y,color);
        }
    }
};
inline Primitive Stroke(float x0,float z0,float x1,float z1,float width,std::array<int,4> color,std::vector<int> required){Primitive p;p.v={x0,z0,x1,z1,x1,z1};p.color={color,color,color};p.required=std::move(required);p.stroke=true;p.width=width;return p;}
}
