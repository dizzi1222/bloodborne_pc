// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "parity_style.h"

// Offline-only analytic coverage for explicitly identified subpixel floor triangles.
// The retained rasterizer and its generation identity remain unchanged.
namespace Atlas2Coverage {
using namespace Atlas2Parity;
struct Point {double x,y;};
inline std::vector<Point> Clip(const std::vector<Point>& input,int axis,double edge,bool greater){
 std::vector<Point> output;if(input.empty())return output;Point previous=input.back();auto value=[&](Point p){return ((axis?p.y:p.x)-edge)*(greater?1:-1);};double before=value(previous);
 for(Point current:input){double after=value(current);if((before>=0)!=(after>=0)){double t=before/(before-after);output.push_back({previous.x+(current.x-previous.x)*t,previous.y+(current.y-previous.y)*t});}if(after>=0)output.push_back(current);previous=current;before=after;}return output;
}
inline std::array<Point,3> Project(const Raster& raster,const Primitive& primitive){
 std::array<Point,3> points;double factor=std::ldexp(1.,-raster.level);
 for(int k=0;k<3;++k){auto p=raster.transform.Image(primitive.v[k*2],primitive.v[k*2+1]);points[k]={p[0]*factor-raster.tx*Tile+Gutter,p[1]*factor-raster.ty*Tile+Gutter};}return points;
}
inline double MinimumAltitude(const Raster& raster,const Primitive& primitive){
 auto p=Project(raster,primitive);double twice=std::abs((p[1].x-p[0].x)*(p[2].y-p[0].y)-(p[1].y-p[0].y)*(p[2].x-p[0].x));double longest=0;for(int k=0;k<3;++k)longest=std::max(longest,std::hypot(p[k].x-p[(k+1)%3].x,p[k].y-p[(k+1)%3].y));return longest>0?twice/longest:0;
}
inline void DrawTriangle(Raster& raster,const Primitive& primitive){
 auto p=Project(raster,primitive);double denominator=(p[1].y-p[2].y)*(p[0].x-p[2].x)+(p[2].x-p[1].x)*(p[0].y-p[2].y);if(std::abs(denominator)<1e-12)return;
 int x0=std::max(0,int(std::floor(std::min({p[0].x,p[1].x,p[2].x})))),x1=std::min(Dimension-1,int(std::ceil(std::max({p[0].x,p[1].x,p[2].x}))));
 int y0=std::max(0,int(std::floor(std::min({p[0].y,p[1].y,p[2].y})))),y1=std::min(Dimension-1,int(std::ceil(std::max({p[0].y,p[1].y,p[2].y}))));double factor=std::ldexp(1.,-raster.level);
 for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x){std::vector<Point> polygon(p.begin(),p.end());polygon=Clip(polygon,0,x,true);polygon=Clip(polygon,0,x+1,false);polygon=Clip(polygon,1,y,true);polygon=Clip(polygon,1,y+1,false);if(polygon.size()<3)continue;
  double twice=0,cx=0,cy=0;for(size_t k=0;k<polygon.size();++k){Point a=polygon[k],b=polygon[(k+1)%polygon.size()];double cross=a.x*b.y-b.x*a.y;twice+=cross;cx+=(a.x+b.x)*cross;cy+=(a.y+b.y)*cross;}if(std::abs(twice)<1e-10)continue;double coverage=std::min(1.,std::abs(twice)*.5);cx/=3*twice;cy/=3*twice;
  double a=((p[1].y-p[2].y)*(cx-p[2].x)+(p[2].x-p[1].x)*(cy-p[2].y))/denominator,b=((p[2].y-p[0].y)*(cx-p[2].x)+(p[0].x-p[2].x)*(cy-p[2].y))/denominator,c=1-a-b;std::array<float,4> color{};for(int channel=0;channel<4;++channel)color[channel]=float(a*primitive.color[0][channel]+b*primitive.color[1][channel]+c*primitive.color[2][channel]);
  if(primitive.textured&&raster.texture){auto world=raster.transform.World((cx+raster.tx*Tile-Gutter)/factor,(cy+raster.ty*Tile-Gutter)/factor);auto sample=raster.texture->Sample(std::clamp(.5f+(float(world[0])-raster.material_x)/raster.material_span,0.f,1.f),std::clamp(.5f+(float(world[1])-raster.material_z)/raster.material_span,0.f,1.f));for(int channel=0;channel<4;++channel)color[channel]*=sample[channel]/255.f;}
  color[3]*=float(coverage);raster.Blend(x,y,color);
 }
}
}
