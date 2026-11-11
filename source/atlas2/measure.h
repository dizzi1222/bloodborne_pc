// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>
namespace Atlas2Measure {
using Clock=std::chrono::steady_clock;
struct Recorder {
    static constexpr size_t Limit=16384;
    bool active=false,overflow=false;uint64_t generation=0;std::string condition;
    Clock::time_point last;std::vector<double> present_ms,map_cpu_ms;double setup_ms=0;
    bool Enabled()const{static bool enabled=[](){const char* e=std::getenv("BB_ATLAS2_MEASURE");return e&&std::string(e)=="1";}();return enabled;}
    void Add(std::vector<double>& values,double ms){if(!std::isfinite(ms)||ms<0)return;if(values.size()<Limit)values.push_back(ms);else overflow=true;}
    void Start(const std::string& label){if(!Enabled()||label.empty()||label.size()>64||label.find_first_not_of("abcdefghijklmnopqrstuvwxyz_0123456789")!=std::string::npos)return;active=true;overflow=false;++generation;condition=label;present_ms.clear();map_cpu_ms.clear();setup_ms=0;last=Clock::now();}
    void Present(){if(!active)return;auto now=Clock::now();Add(present_ms,std::chrono::duration<double,std::milli>(now-last).count());last=now;}
    nlohmann::json State()const{return {{"enabled",Enabled()},{"active",active},{"generation",generation},{"condition",condition},{"present_samples",present_ms.size()},{"map_cpu_samples",map_cpu_ms.size()},{"overflow",overflow}};}
    nlohmann::json Result()const{return {{"schema",1},{"generation",generation},{"condition",condition},{"present_interval_ms",present_ms},{"map_cpu_elapsed_ms",map_cpu_ms},{"setup_cpu_elapsed_ms",setup_ms},{"sample_limit",Limit},{"overflow",overflow},{"present_clock","BbMap::PollTestCommands entry, once per BbOverlay::NotePresent"},{"gpu_timestamp_measured",false}};}
};
struct Scope {
    Recorder& recorder;Clock::time_point start;bool active;
    explicit Scope(Recorder& r):recorder(r),start(Clock::now()),active(r.active){}
    ~Scope(){if(active&&recorder.active)recorder.Add(recorder.map_cpu_ms,std::chrono::duration<double,std::milli>(Clock::now()-start).count());}
};
}
