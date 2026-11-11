// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "imgui.h"
#include <nlohmann/json.hpp>
#include <string>
namespace BbMapStatic {
bool Enabled();
bool Load(const std::string& region);
int Select(const std::string& region,float x,float y,float z,bool valid,bool continuity=true);
int StrictLayer(const std::string& region,float x,float y,float z,bool valid);
int Primary(const std::string& region);
void Draw(ImDrawList* draw,const std::string& region,int layer,ImVec2 center,ImVec2 extent,float cx,float cz,float zoom,float opacity=1,bool shading=true,float ui_scale=1);
void Command(const std::string& command);
int ManualLayer();
int Mode(); // 0=static, 1=reference, 2=overlay
nlohmann::json Stats();
nlohmann::json ProjectionMetrics(float x,float z,float zoom);
void Shutdown();
}
