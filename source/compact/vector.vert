#version 450
layout(location=0) in vec2 position;
layout(location=1) in vec2 auxiliary;
layout(location=2) in vec4 colour;
layout(location=0) out vec4 outColour;
layout(location=1) out vec2 outUV;
layout(push_constant) uniform Constants {vec4 view;vec4 data;vec4 paint;vec4 params;} p;
void main() {
 vec2 projected=position*p.view.xy+p.view.zw;
 if(p.data.w>3.5) {
  outColour=p.paint;outUV=auxiliary;
 } else if(p.data.w>2.5) {
  // Stable world-space grain, clipped to exact source-derived polygon triangles.
  vec2 world=vec2(position.x,-position.y);
  float broad=sin(world.x*.31+sin(world.y*.18))*sin(world.y*.29+sin(world.x*.13));
  float fine=fract(sin(dot(world,vec2(12.9898,78.233)))*43758.5453);
  float grain=.90+.075*broad+.025*fine;
  outColour=vec4(p.paint.rgb*grain,p.paint.a);
  outUV=fract(world*.035);
 } else if(p.data.w>1.5) {
  float distance=colour.a<0.5?p.params.z*0.5+0.5:max(0.0,p.params.z*0.5-0.5);
  projected+=auxiliary*p.params.xy*distance;
  float alpha=p.paint.a+(p.params.w>1.5?colour.g:(p.params.w>0.5?colour.r:0.0));
  outColour=vec4(p.paint.rgb,alpha*colour.a);outUV=vec2(0.5);
 } else if(p.data.w>0.5) {
  float t=p.paint.w>0.5?clamp((auxiliary.x-p.paint.x)/max(0.01,p.paint.y-p.paint.x),0.0,1.0):0.72;
  float shade=118.0+float(int(120.0*t));
  outColour=vec4((vec3(shade)+vec3(4,2,0))/255.0,p.paint.z);
  outUV=clamp(vec2(0.5)+(vec2(position.x,-position.y)-p.data.xy)/p.data.z,vec2(0),vec2(1));
 } else {outColour=p.paint;outUV=vec2(0.5);}
 gl_Position=vec4(projected,0,1);
}
