#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

namespace {

constexpr int kSampleRate = 48000;
constexpr int kInputChannels = 16;
constexpr int kOutputChannels = 2;
constexpr int kDryDelaySamples = 172;
constexpr double kLfeLowpassCutoffHz = 125.0;
constexpr int kDefaultCapacityFrames = 8192;
constexpr double kPi = 3.141592653589793238462643383279502884;

constexpr int kLfeChannelIndex = 3;
constexpr float kSurroundFillThreshold = 1e-4f;
constexpr float kChannelSanityThreshold = 1e-4f;
constexpr double kChannelSanityCorrelation = 0.995;
constexpr int kChannelSanityMinDuplicates = 3;
constexpr float kUpmix916Threshold = 1e-4f;
constexpr double kUpmixAirHighpassHz = 3500.0;
constexpr float kGeneratedChannelGain = 0.5011872336272722f;
constexpr int kWindows71Channels = 8;
constexpr int kUpmixScratchChannels = 24;
constexpr int kDecorStages = 4;
constexpr int kMaxPeqFilters = 32;
constexpr int kPeqCoeffCount = 5;
constexpr int kPeqCrossfadeSamples = 128;
constexpr double kPeqDenormalGuard = 1e-30;
constexpr float kTrimMinDb = -24.0f;
constexpr float kTrimMaxDb = 0.0f;

enum class LayoutKind : int32_t {
    Windows71 = 0,
    Sharur916 = 1,
};

constexpr std::array<double, 2> kButterworthQ = {
    0.541196100146197,
    1.3065629648763766,
};

constexpr std::array<std::array<double, kDecorStages>, 8> kDecorCoeffs = {{
    {{0.57, -0.49, 0.63, -0.41}},
    {{-0.46, 0.61, -0.38, 0.54}},
    {{0.52, -0.67, 0.46, -0.59}},
    {{-0.62, 0.43, -0.55, 0.36}},
    {{0.49, -0.58, 0.37, -0.66}},
    {{-0.53, 0.39, -0.61, 0.48}},
    {{0.44, -0.64, 0.56, -0.35}},
    {{-0.59, 0.51, -0.42, 0.63}},
}};

constexpr std::array<std::array<double, 2>, kInputChannels> kSharur916Matrix = {{
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{0.70710678, 0.70710678}},
    {{2.26464431, 2.26464431}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
}};

constexpr std::array<std::array<double, 2>, kWindows71Channels> kWindows71Matrix = {{
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{0.70710678, 0.70710678}},
    {{2.26464431, 2.26464431}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
    {{1.0, 0.0}},
    {{0.0, 1.0}},
}};

constexpr double kSoundEnhancerMakeupGain = 2.371373705661655; // +7.5 dB
constexpr double kSoundEnhancerCeiling = 0.8912509381337456; // -1.0 dBFS
constexpr double kSoundEnhancerAttackAlpha = 0.85;
constexpr double kSoundEnhancerReleaseAlpha = 0.08;
constexpr std::array<double, 3> kSoundEnhancerTruePeakFractions = {{0.25, 0.5, 0.75}};
constexpr uint32_t kSoundEnhancerGainRampSamples = 64;

struct NativeDspSnapshot {
    float channelLevels[kInputChannels];
    float channelRms[kInputChannels];
    float rawChannelLevels[kInputChannels];
    float rawChannelRms[kInputChannels];
    float leftMeter;
    float rightMeter;
    float preampDb;
    float trimLeftDb;
    float trimRightDb;
    float limiterGain;
    int32_t clipping;
    float userVolume;
    float masterVolume;
    int32_t masterMuted;
    int32_t surroundFillEnabled;
    int32_t surroundFillActive;
    int32_t upmix916Enabled;
    int32_t upmix916Active;
    int32_t channelSanityEnabled;
    int32_t channelSanityActive;
    int32_t soundEnhancerEnabled;
    float soundEnhancerGain;
};

struct NativeEngineSnapshot {
    int32_t running;
    int32_t inputChannels;
    int32_t callbackStatusCount;
    int32_t dspErrorCount;
    uint64_t callbackInvocationCount;
    uint64_t processedFrameCount;
    int32_t mmcssRegistered;
    float cpuLoad;
    float inputLatency;
    float outputLatency;
    int32_t hasLatency;
    char status[256];
    char route[512];
    char callbackStatus[256];
    char streamProfile[32];
    NativeDspSnapshot dsp;
};

struct NativeDeviceDescriptor {
    char endpointId[512];
    char name[256];
    int32_t direction;
    int32_t isDefault;
    int32_t maxInputChannels;
    int32_t maxOutputChannels;
    int32_t defaultSamplerate;
    int32_t ambiguous;
};

template <size_t N>
void copy_text(char (&dest)[N], const std::string& text) {
    std::memset(dest, 0, N);
    std::strncpy(dest, text.c_str(), N - 1);
}

#if defined(_WIN32)
struct MmcssApi {
    using SetCharacteristicsFn = HANDLE(WINAPI*)(LPCWSTR, LPDWORD);
    using SetPriorityFn = BOOL(WINAPI*)(HANDLE, int);
    using RevertFn = BOOL(WINAPI*)(HANDLE);

    HMODULE module = nullptr;
    SetCharacteristicsFn setCharacteristics = nullptr;
    SetPriorityFn setPriority = nullptr;
    RevertFn revert = nullptr;
    bool ready = false;
};

MmcssApi& mmcss_api() {
    static MmcssApi api = [] {
        MmcssApi loaded;
        loaded.module = LoadLibraryW(L"Avrt.dll");
        if (loaded.module == nullptr) {
            return loaded;
        }
        loaded.setCharacteristics = reinterpret_cast<MmcssApi::SetCharacteristicsFn>(
            GetProcAddress(loaded.module, "AvSetMmThreadCharacteristicsW")
        );
        loaded.setPriority = reinterpret_cast<MmcssApi::SetPriorityFn>(
            GetProcAddress(loaded.module, "AvSetMmThreadPriority")
        );
        loaded.revert = reinterpret_cast<MmcssApi::RevertFn>(
            GetProcAddress(loaded.module, "AvRevertMmThreadCharacteristics")
        );
        loaded.ready = loaded.setCharacteristics != nullptr;
        return loaded;
    }();
    return api;
}

void prepare_mmcss_api() {
    (void)mmcss_api();
}

struct MmcssThreadRegistration {
    bool attempted = false;
    HANDLE taskHandle = nullptr;

    ~MmcssThreadRegistration() {
        if (taskHandle == nullptr) {
            return;
        }
        auto& api = mmcss_api();
        if (api.revert != nullptr) {
            api.revert(taskHandle);
        }
        taskHandle = nullptr;
    }
};

bool register_current_thread_mmcss() {
    thread_local MmcssThreadRegistration registration;
    if (registration.attempted) {
        return registration.taskHandle != nullptr;
    }
    registration.attempted = true;

    auto& api = mmcss_api();
    if (!api.ready) {
        return false;
    }
    DWORD taskIndex = 0;
    registration.taskHandle = api.setCharacteristics(L"Pro Audio", &taskIndex);
    if (registration.taskHandle != nullptr && api.setPriority != nullptr) {
        constexpr int kAvrtPriorityCritical = 2;
        api.setPriority(registration.taskHandle, kAvrtPriorityCritical);
    }
    return registration.taskHandle != nullptr;
}
#else
void prepare_mmcss_api() {}
bool register_current_thread_mmcss() {
    return false;
}
#endif

void append_utf8_codepoint(std::string& out, uint32_t codepoint) {
    if (codepoint <= 0x7F) {
        out.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7FF) {
        out.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
        out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else if (codepoint <= 0xFFFF) {
        out.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
        out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else {
        out.push_back(static_cast<char>(0xF0 | (codepoint >> 18)));
        out.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    }
}

std::string wasapi_id_to_utf8(const ma_device_id& id) {
    std::string out;
    constexpr size_t wasapiIdLength = sizeof(id.wasapi) / sizeof(id.wasapi[0]);
    for (size_t i = 0; i < wasapiIdLength && id.wasapi[i] != 0; ++i) {
        uint32_t codepoint = static_cast<uint32_t>(id.wasapi[i]);
        if (codepoint >= 0xD800 && codepoint <= 0xDBFF && i + 1 < wasapiIdLength) {
            const uint32_t low = static_cast<uint32_t>(id.wasapi[i + 1]);
            if (low >= 0xDC00 && low <= 0xDFFF) {
                codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00);
                ++i;
            }
        }
        append_utf8_codepoint(out, codepoint);
    }
    return out;
}

int32_t max_native_channels(const ma_device_info& info) {
    int32_t maxChannels = 0;
    for (ma_uint32 i = 0; i < info.nativeDataFormatCount; ++i) {
        const ma_uint32 channels = info.nativeDataFormats[i].channels;
        if (channels > static_cast<ma_uint32>(maxChannels)) {
            maxChannels = static_cast<int32_t>(channels);
        }
    }
    return maxChannels;
}

int32_t first_native_samplerate(const ma_device_info& info) {
    for (ma_uint32 i = 0; i < info.nativeDataFormatCount; ++i) {
        if (info.nativeDataFormats[i].sampleRate != 0) {
            return static_cast<int32_t>(info.nativeDataFormats[i].sampleRate);
        }
    }
    return kSampleRate;
}

void fill_device_descriptor(NativeDeviceDescriptor& out, const ma_device_info& info, int32_t direction) {
    std::memset(&out, 0, sizeof(out));
    copy_text(out.endpointId, wasapi_id_to_utf8(info.id));
    copy_text(out.name, info.name);
    out.direction = direction;
    out.isDefault = info.isDefault ? 1 : 0;
    out.maxInputChannels = direction == 1 ? max_native_channels(info) : 0;
    out.maxOutputChannels = direction == 0 ? max_native_channels(info) : 0;
    out.defaultSamplerate = first_native_samplerate(info);
    out.ambiguous = 0;
}

double db_to_linear(double db) {
    return std::pow(10.0, db / 20.0);
}

float clamp_trim_db(float db) {
    if (!std::isfinite(db)) {
        return 0.0f;
    }
    return std::clamp(db, kTrimMinDb, kTrimMaxDb);
}

uint32_t normalize_sample_rate(uint32_t sampleRate) {
    if (sampleRate == 48000 || sampleRate == 96000 || sampleRate == 192000) {
        return sampleRate;
    }
    return static_cast<uint32_t>(kSampleRate);
}

uint32_t dry_delay_samples_for_rate(uint32_t sampleRate) {
    const uint32_t rate = std::max<uint32_t>(1, normalize_sample_rate(sampleRate));
    const double scaled = static_cast<double>(kDryDelaySamples) * static_cast<double>(rate) / static_cast<double>(kSampleRate);
    return std::max<uint32_t>(1, static_cast<uint32_t>(std::llround(scaled)));
}

std::string ascii_lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return text;
}

std::string device_notification_text(ma_device_notification_type type) {
    switch (type) {
        case ma_device_notification_type_started:
            return "device started";
        case ma_device_notification_type_stopped:
            return "device stopped";
        case ma_device_notification_type_rerouted:
            return "device rerouted";
        case ma_device_notification_type_interruption_began:
            return "device interruption began";
        case ma_device_notification_type_interruption_ended:
            return "device interruption ended";
        case ma_device_notification_type_unlocked:
            return "device unlocked";
        default:
            return "device notification";
    }
}

std::string compact_device_name(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (unsigned char c : text) {
        if (std::isalnum(c)) {
            out.push_back(static_cast<char>(std::tolower(c)));
        }
    }
    return out;
}

int device_match_score(const std::string& requested, const char* candidateName) {
    const std::string candidate(candidateName ? candidateName : "");
    if (requested.empty() || candidate.empty()) {
        return 0;
    }

    const std::string reqLower = ascii_lower(requested);
    const std::string candLower = ascii_lower(candidate);
    if (reqLower == candLower) {
        return 1000;
    }
    if (candLower.find(reqLower) != std::string::npos || reqLower.find(candLower) != std::string::npos) {
        return 700;
    }

    const std::string reqCompact = compact_device_name(requested);
    const std::string candCompact = compact_device_name(candidate);
    if (!reqCompact.empty() && !candCompact.empty()) {
        if (reqCompact == candCompact) {
            return 650;
        }
        if (candCompact.find(reqCompact) != std::string::npos || reqCompact.find(candCompact) != std::string::npos) {
            return 500;
        }
    }

    int keywordScore = 0;
    for (const std::string& word : {"cable", "vb", "qudelix", "realtek", "speakers", "headphones", "dac", "usb"}) {
        if (reqLower.find(word) != std::string::npos && candLower.find(word) != std::string::npos) {
            keywordScore += 20;
        }
    }
    return keywordScore;
}

struct DeviceSelection {
    ma_device_info* info = nullptr;
    bool ambiguous = false;
    bool endpointRequested = false;
};

DeviceSelection select_device(
    ma_device_info* infos,
    ma_uint32 count,
    const std::string& endpointId,
    const std::string& requestedName
) {
    DeviceSelection selection;
    selection.endpointRequested = !endpointId.empty();
    if (selection.endpointRequested) {
        for (ma_uint32 i = 0; i < count; ++i) {
            if (wasapi_id_to_utf8(infos[i].id) == endpointId) {
                selection.info = &infos[i];
                return selection;
            }
        }
        return selection;
    }

    int bestScore = 0;
    for (ma_uint32 i = 0; i < count; ++i) {
        const int score = device_match_score(requestedName, infos[i].name);
        if (score > bestScore) {
            bestScore = score;
            selection.info = &infos[i];
            selection.ambiguous = false;
        } else if (score > 0 && score == bestScore) {
            selection.ambiguous = true;
        }
    }
    if (bestScore <= 0 || selection.ambiguous) {
        selection.info = nullptr;
    }
    return selection;
}

struct LowpassSection {
    double b0 = 0.0;
    double b1 = 0.0;
    double b2 = 0.0;
    double a1 = 0.0;
    double a2 = 0.0;
};

struct PeqBiquad {
    double b0 = 1.0;
    double b1 = 0.0;
    double b2 = 0.0;
    double a1 = 0.0;
    double a2 = 0.0;
};

struct PeqCascadeConfig {
    int32_t enabled = 0;
    double preampGain = 1.0;
    int32_t count = 0;
    std::array<PeqBiquad, kMaxPeqFilters> filters{};

    bool active() const {
        return enabled != 0 && (count > 0 || std::abs(preampGain - 1.0) > 1e-12);
    }
};

struct PeqConfig {
    PeqCascadeConfig global;
    PeqCascadeConfig speakerLeft;
    PeqCascadeConfig speakerRight;
    int32_t speakerEnabled = 0;
    int32_t swapEnabled = 0;
    uint64_t generation = 0;

    bool bypassed() const {
        return !global.active()
            && !(speakerEnabled != 0 && (speakerLeft.active() || speakerRight.active()))
            && swapEnabled == 0;
    }
};

struct PeqBiquadState {
    double z1 = 0.0;
    double z2 = 0.0;
};

struct PeqRuntimeState {
    std::array<std::array<PeqBiquadState, kMaxPeqFilters>, kOutputChannels> global{};
    std::array<PeqBiquadState, kMaxPeqFilters> speakerLeft{};
    std::array<PeqBiquadState, kMaxPeqFilters> speakerRight{};
};

class DownmixDsp {
public:
    DownmixDsp() {
        std::shared_ptr<const PeqConfig> initialPeq = std::make_shared<PeqConfig>();
        std::atomic_store_explicit(&publishedPeqConfig_, initialPeq, std::memory_order_release);
        peqActiveConfig_ = initialPeq;
        set_sample_rate(static_cast<uint32_t>(kSampleRate));
        reserve(kDefaultCapacityFrames);
        reset_runtime_state();
        publish_static_config();
    }

    void reserve(int frames) {
        const int desired = std::max(kDefaultCapacityFrames, frames);
        if (desired <= capacityFrames_) {
            return;
        }
        capacityFrames_ = desired;
        input_.assign(static_cast<size_t>(capacityFrames_) * kInputChannels, 0.0f);
        effective_.assign(static_cast<size_t>(capacityFrames_) * kInputChannels, 0.0f);
        renderBus_.assign(static_cast<size_t>(capacityFrames_) * kInputChannels, 0.0f);
        processed_.assign(static_cast<size_t>(capacityFrames_) * kInputChannels, 0.0f);
        stereo_.assign(static_cast<size_t>(capacityFrames_) * kOutputChannels, 0.0);
        peqOldStereo_.assign(static_cast<size_t>(capacityFrames_) * kOutputChannels, 0.0);
        lfeScratch_.assign(capacityFrames_, 0.0f);
        upmixScratch_.assign(static_cast<size_t>(capacityFrames_) * kUpmixScratchChannels, 0.0f);
    }

    void set_preamp_db(float db) {
        preampDb_.store(db, std::memory_order_relaxed);
        preampGain_.store(static_cast<float>(db_to_linear(db)), std::memory_order_relaxed);
        snapshotPreampDb_.store(db, std::memory_order_relaxed);
    }

    void set_master_volume(float scalar, bool muted) {
        const float clamped = std::clamp(scalar, 0.0f, 1.0f);
        masterVolume_.store(clamped, std::memory_order_relaxed);
        masterMuted_.store(muted ? 1 : 0, std::memory_order_relaxed);
        snapshotMasterVolume_.store(clamped, std::memory_order_relaxed);
        snapshotMasterMuted_.store(muted ? 1 : 0, std::memory_order_relaxed);
    }

    void set_user_volume(float scalar) {
        const float clamped = std::clamp(scalar, 0.0f, 1.0f);
        userVolume_.store(clamped, std::memory_order_relaxed);
        snapshotUserVolume_.store(clamped, std::memory_order_relaxed);
    }

    void set_sample_rate(uint32_t sampleRate) {
        const uint32_t normalized = normalize_sample_rate(sampleRate);
        if (normalized == sampleRate_ && dryDelay_.size() == static_cast<size_t>(dryDelaySamples_) * kInputChannels) {
            return;
        }
        sampleRate_ = normalized;
        dryDelaySamples_ = dry_delay_samples_for_rate(normalized);
        dryDelay_.assign(static_cast<size_t>(dryDelaySamples_) * kInputChannels, 0.0f);
        build_lfe_filter();
        reset_runtime_state();
    }

    void set_channel_trim_db(float leftDb, float rightDb) {
        const float left = clamp_trim_db(leftDb);
        const float right = clamp_trim_db(rightDb);
        trimLeftDb_.store(left, std::memory_order_relaxed);
        trimRightDb_.store(right, std::memory_order_relaxed);
        trimLeftGain_.store(static_cast<float>(db_to_linear(left)), std::memory_order_relaxed);
        trimRightGain_.store(static_cast<float>(db_to_linear(right)), std::memory_order_relaxed);
        snapshotTrimLeftDb_.store(left, std::memory_order_relaxed);
        snapshotTrimRightDb_.store(right, std::memory_order_relaxed);
    }

    void set_surround_fill_enabled(bool enabled) {
        surroundFillEnabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
        snapshotSurroundFillEnabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
    }

    void set_upmix_916_enabled(bool enabled) {
        upmix916Enabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
        snapshotUpmix916Enabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
    }

    void set_channel_sanity_enabled(bool enabled) {
        channelSanityEnabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
        snapshotChannelSanityEnabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
    }

    void set_sound_enhancer_enabled(bool enabled) {
        soundEnhancerEnabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
        soundEnhancerResetPending_.store(1, std::memory_order_release);
        snapshotSoundEnhancerEnabled_.store(enabled ? 1 : 0, std::memory_order_relaxed);
        snapshotSoundEnhancerGain_.store(1.0f, std::memory_order_relaxed);
    }

    void set_monitor_layout(int32_t layout) {
        monitorLayout_.store(layout == static_cast<int32_t>(LayoutKind::Sharur916) ? layout : 0, std::memory_order_relaxed);
    }

    void set_input_layout(int32_t layout) {
        inputLayout_.store(layout == static_cast<int32_t>(LayoutKind::Sharur916) ? layout : 0, std::memory_order_relaxed);
    }

    void set_peq_config(
        int32_t globalEnabled,
        const double* globalCoeffs,
        uint32_t globalCount,
        double globalPreampDb,
        int32_t speakerEnabled,
        const double* speakerLeftCoeffs,
        uint32_t speakerLeftCount,
        double speakerLeftPreampDb,
        const double* speakerRightCoeffs,
        uint32_t speakerRightCount,
        double speakerRightPreampDb,
        int32_t swapEnabled
    ) {
        auto next = std::make_shared<PeqConfig>();
        next->generation = peqGeneration_.fetch_add(1, std::memory_order_relaxed) + 1;
        next->speakerEnabled = speakerEnabled != 0 ? 1 : 0;
        next->swapEnabled = swapEnabled != 0 ? 1 : 0;
        fill_peq_cascade(next->global, globalEnabled, globalCoeffs, globalCount, globalPreampDb);
        fill_peq_cascade(next->speakerLeft, speakerEnabled, speakerLeftCoeffs, speakerLeftCount, speakerLeftPreampDb);
        fill_peq_cascade(next->speakerRight, speakerEnabled, speakerRightCoeffs, speakerRightCount, speakerRightPreampDb);
        std::shared_ptr<const PeqConfig> published = next;
        std::atomic_store_explicit(&publishedPeqConfig_, published, std::memory_order_release);
    }

    void reset_runtime_state() {
        limiterGain_ = 1.0;
        std::fill(dryDelay_.begin(), dryDelay_.end(), 0.0f);
        for (auto& sectionState : lfeState_) {
            sectionState = {0.0, 0.0};
        }
        for (auto& row : decorX1_) {
            row.fill(0.0);
        }
        for (auto& row : decorY1_) {
            row.fill(0.0);
        }
        hpX1_.fill(0.0);
        hpY1_.fill(0.0);
        lpY1_.fill(0.0);
        soundEnhancerResetPending_.store(1, std::memory_order_release);
        snapshotLimiterGain_.store(1.0f, std::memory_order_relaxed);
        snapshotSoundEnhancerGain_.store(1.0f, std::memory_order_relaxed);
        snapshotClipping_.store(0, std::memory_order_relaxed);
        snapshotSurroundFillActive_.store(0, std::memory_order_relaxed);
        snapshotUpmix916Active_.store(0, std::memory_order_relaxed);
        snapshotChannelSanityActive_.store(0, std::memory_order_relaxed);
        peqActiveState_ = PeqRuntimeState{};
        peqTransitionState_ = PeqRuntimeState{};
        peqTransitionConfig_.reset();
        peqCrossfadeRemaining_ = 0;
    }

    bool process(const float* in, uint32_t frames, int inputChannels, float* out) {
        if (out == nullptr) {
            return false;
        }
        if (frames == 0) {
            return true;
        }
        if (frames > static_cast<uint32_t>(capacityFrames_)) {
            std::fill(out, out + static_cast<size_t>(frames) * kOutputChannels, 0.0f);
            return false;
        }
        if (in == nullptr) {
            std::fill(out, out + static_cast<size_t>(frames) * kOutputChannels, 0.0f);
            publish_zero_levels();
            return true;
        }

        prepare_input(in, frames, inputChannels);
        measure_levels(input_.data(), frames, workRawLevels_, workRawRms_);

        const bool surroundFillEnabled = surroundFillEnabled_.load(std::memory_order_relaxed) != 0;
        const bool upmix916Enabled = upmix916Enabled_.load(std::memory_order_relaxed) != 0;
        const bool channelSanityEnabled = channelSanityEnabled_.load(std::memory_order_relaxed) != 0;
        const LayoutKind monitorLayout = monitorLayout_.load(std::memory_order_relaxed) == 1
            ? LayoutKind::Sharur916
            : LayoutKind::Windows71;
        const LayoutKind inputLayout = inputLayout_.load(std::memory_order_relaxed) == 1
            ? LayoutKind::Sharur916
            : LayoutKind::Windows71;

        bool surroundFillActive = false;
        bool upmix916Active = false;
        bool channelSanityActive = false;
        const float* sourceField = input_.data();
        if (surroundFillEnabled || channelSanityEnabled) {
            const size_t sampleCount = static_cast<size_t>(frames) * kInputChannels;
            std::copy(input_.begin(), input_.begin() + sampleCount, effective_.begin());
            channelSanityActive = apply_channel_sanity(effective_.data(), frames, channelSanityEnabled);
            if (inputLayout == LayoutKind::Windows71) {
                surroundFillActive = apply_surround_fill(effective_.data(), frames, surroundFillEnabled);
            }
            sourceField = effective_.data();
        }

        const float* renderField = sourceField;
        if (monitorLayout == LayoutKind::Sharur916) {
            build_sharur_916_bus(sourceField, frames, inputChannels, inputLayout);
            upmix916Active = generate_missing_sharur_916(renderBus_.data(), frames, sourceField, inputChannels, inputLayout, upmix916Enabled);
            renderField = renderBus_.data();
        }

        measure_levels(renderField, frames, workLevels_, workRms_);

        apply_sharur_processing(renderField, frames);

        const double preampGain = static_cast<double>(preampGain_.load(std::memory_order_relaxed));
        const double userVolume = static_cast<double>(userVolume_.load(std::memory_order_relaxed));
        const double masterVolume = static_cast<double>(masterVolume_.load(std::memory_order_relaxed));
        const double trimLeftGain = static_cast<double>(trimLeftGain_.load(std::memory_order_relaxed));
        const double trimRightGain = static_cast<double>(trimRightGain_.load(std::memory_order_relaxed));
        const bool masterMuted = masterMuted_.load(std::memory_order_relaxed) != 0;
        const bool soundEnhancerEnabled = soundEnhancerEnabled_.load(std::memory_order_relaxed) != 0;
        const float preampDb = preampDb_.load(std::memory_order_relaxed);
        const float trimLeftDb = trimLeftDb_.load(std::memory_order_relaxed);
        const float trimRightDb = trimRightDb_.load(std::memory_order_relaxed);

        double peakBeforeLimiter = 0.0;
        if (monitorLayout == LayoutKind::Sharur916) {
            for (uint32_t frame = 0; frame < frames; ++frame) {
                double left = 0.0;
                double right = 0.0;
                const float* row = &processed_[static_cast<size_t>(frame) * kInputChannels];
                for (int ch = 0; ch < kInputChannels; ++ch) {
                    left += static_cast<double>(row[ch]) * kSharur916Matrix[ch][0];
                    right += static_cast<double>(row[ch]) * kSharur916Matrix[ch][1];
                }
                left *= preampGain;
                right *= preampGain;
                stereo_[static_cast<size_t>(frame) * 2] = left;
                stereo_[static_cast<size_t>(frame) * 2 + 1] = right;
            }
        } else {
            for (uint32_t frame = 0; frame < frames; ++frame) {
                double left = 0.0;
                double right = 0.0;
                const float* row = &processed_[static_cast<size_t>(frame) * kInputChannels];
                for (int ch = 0; ch < kWindows71Channels; ++ch) {
                    left += static_cast<double>(row[ch]) * kWindows71Matrix[ch][0];
                    right += static_cast<double>(row[ch]) * kWindows71Matrix[ch][1];
                }
                left *= preampGain;
                right *= preampGain;
                stereo_[static_cast<size_t>(frame) * 2] = left;
                stereo_[static_cast<size_t>(frame) * 2 + 1] = right;
            }
        }
        apply_peq_routing(frames);
        if (trimLeftGain != 1.0 || trimRightGain != 1.0) {
            for (uint32_t frame = 0; frame < frames; ++frame) {
                const size_t stereoIndex = static_cast<size_t>(frame) * 2;
                stereo_[stereoIndex] *= trimLeftGain;
                stereo_[stereoIndex + 1] *= trimRightGain;
            }
        }
        bool soundEnhancerLimited = false;
        double soundEnhancerGain = 1.0;
        if (soundEnhancerResetPending_.exchange(0, std::memory_order_acq_rel) != 0) {
            soundEnhancerSafetyGain_ = 1.0;
            soundEnhancerAppliedGain_ = 1.0;
        }
        if (soundEnhancerEnabled) {
            soundEnhancerGain = apply_sound_enhancer(frames, soundEnhancerLimited);
        } else {
            soundEnhancerSafetyGain_ = 1.0;
            soundEnhancerAppliedGain_ = 1.0;
        }
        peakBeforeLimiter = peak_stereo(frames);

        double targetGain = 1.0;
        bool clipping = soundEnhancerLimited;
        if (peakBeforeLimiter > 1.0) {
            targetGain = 1.0 / peakBeforeLimiter;
            clipping = true;
        }
        const double alpha = targetGain < limiterGain_ ? 0.4 : 0.05;
        const double smoothedGain = (1.0 - alpha) * limiterGain_ + alpha * targetGain;
        const double appliedLimiterGain = clipping ? std::min(smoothedGain, targetGain) : smoothedGain;
        limiterGain_ = smoothedGain;

        const double finalGain = masterMuted ? 0.0 : (masterVolume * userVolume);
        double leftMeter = 0.0;
        double rightMeter = 0.0;
        for (uint32_t frame = 0; frame < frames; ++frame) {
            const size_t stereoIndex = static_cast<size_t>(frame) * 2;
            const float left = static_cast<float>(stereo_[stereoIndex] * appliedLimiterGain * finalGain);
            const float right = static_cast<float>(stereo_[stereoIndex + 1] * appliedLimiterGain * finalGain);
            out[stereoIndex] = left;
            out[stereoIndex + 1] = right;
            leftMeter = std::max(leftMeter, std::abs(static_cast<double>(left)));
            rightMeter = std::max(rightMeter, std::abs(static_cast<double>(right)));
        }

        publish_snapshot(
            static_cast<float>(leftMeter),
            static_cast<float>(rightMeter),
            preampDb,
            trimLeftDb,
            trimRightDb,
            static_cast<float>(userVolume),
            static_cast<float>(masterVolume),
            masterMuted,
            surroundFillEnabled,
            surroundFillActive,
            upmix916Enabled,
            upmix916Active,
            channelSanityEnabled,
            channelSanityActive,
            soundEnhancerEnabled,
            static_cast<float>(soundEnhancerGain),
            clipping
        );
        return true;
    }

    void snapshot(NativeDspSnapshot& out) const {
        for (int i = 0; i < kInputChannels; ++i) {
            out.channelLevels[i] = snapshotLevels_[i].load(std::memory_order_relaxed);
            out.channelRms[i] = snapshotRms_[i].load(std::memory_order_relaxed);
            out.rawChannelLevels[i] = snapshotRawLevels_[i].load(std::memory_order_relaxed);
            out.rawChannelRms[i] = snapshotRawRms_[i].load(std::memory_order_relaxed);
        }
        out.leftMeter = snapshotLeftMeter_.load(std::memory_order_relaxed);
        out.rightMeter = snapshotRightMeter_.load(std::memory_order_relaxed);
        out.preampDb = snapshotPreampDb_.load(std::memory_order_relaxed);
        out.trimLeftDb = snapshotTrimLeftDb_.load(std::memory_order_relaxed);
        out.trimRightDb = snapshotTrimRightDb_.load(std::memory_order_relaxed);
        out.limiterGain = snapshotLimiterGain_.load(std::memory_order_relaxed);
        out.clipping = snapshotClipping_.load(std::memory_order_relaxed);
        out.userVolume = snapshotUserVolume_.load(std::memory_order_relaxed);
        out.masterVolume = snapshotMasterVolume_.load(std::memory_order_relaxed);
        out.masterMuted = snapshotMasterMuted_.load(std::memory_order_relaxed);
        out.surroundFillEnabled = snapshotSurroundFillEnabled_.load(std::memory_order_relaxed);
        out.surroundFillActive = snapshotSurroundFillActive_.load(std::memory_order_relaxed);
        out.upmix916Enabled = snapshotUpmix916Enabled_.load(std::memory_order_relaxed);
        out.upmix916Active = snapshotUpmix916Active_.load(std::memory_order_relaxed);
        out.channelSanityEnabled = snapshotChannelSanityEnabled_.load(std::memory_order_relaxed);
        out.channelSanityActive = snapshotChannelSanityActive_.load(std::memory_order_relaxed);
        out.soundEnhancerEnabled = snapshotSoundEnhancerEnabled_.load(std::memory_order_relaxed);
        out.soundEnhancerGain = snapshotSoundEnhancerGain_.load(std::memory_order_relaxed);
    }

private:
    static float& sample(float* data, uint32_t frame, int channel) {
        return data[static_cast<size_t>(frame) * kInputChannels + channel];
    }

    static const float& sample(const float* data, uint32_t frame, int channel) {
        return data[static_cast<size_t>(frame) * kInputChannels + channel];
    }

    float* scratch(int slot) {
        return &upmixScratch_[static_cast<size_t>(slot) * capacityFrames_];
    }

    static double sanitize_denormal(double value) {
        return std::abs(value) < kPeqDenormalGuard ? 0.0 : value;
    }

    static void fill_peq_cascade(
        PeqCascadeConfig& cascade,
        int32_t enabled,
        const double* coeffs,
        uint32_t count,
        double preampDb
    ) {
        cascade = PeqCascadeConfig{};
        cascade.enabled = enabled != 0 ? 1 : 0;
        cascade.preampGain = std::isfinite(preampDb) ? db_to_linear(std::clamp(preampDb, -24.0, 24.0)) : 1.0;
        const uint32_t safeCount = std::min<uint32_t>(count, kMaxPeqFilters);
        if (coeffs == nullptr) {
            cascade.count = 0;
            return;
        }
        for (uint32_t index = 0; index < safeCount; ++index) {
            const double* row = coeffs + static_cast<size_t>(index) * kPeqCoeffCount;
            bool finite = true;
            for (int item = 0; item < kPeqCoeffCount; ++item) {
                finite = finite && std::isfinite(row[item]);
            }
            if (!finite) {
                continue;
            }
            auto& out = cascade.filters[static_cast<size_t>(cascade.count)];
            out.b0 = row[0];
            out.b1 = row[1];
            out.b2 = row[2];
            out.a1 = row[3];
            out.a2 = row[4];
            cascade.count += 1;
        }
    }

    double peak_stereo(uint32_t frames) const {
        double peak = 0.0;
        for (uint32_t frame = 0; frame < frames; ++frame) {
            const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
            peak = std::max(peak, std::abs(stereo_[stereoIndex]));
            peak = std::max(peak, std::abs(stereo_[stereoIndex + 1]));
        }
        return peak;
    }

    static double catmull_rom_sample(double p0, double p1, double p2, double p3, double frac) {
        const double frac2 = frac * frac;
        const double frac3 = frac2 * frac;
        return 0.5 * (
            (2.0 * p1)
            + ((-p0 + p2) * frac)
            + ((2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * frac2)
            + ((-p0 + 3.0 * p1 - 3.0 * p2 + p3) * frac3)
        );
    }

    double estimated_true_peak_stereo(uint32_t frames) const {
        double peak = peak_stereo(frames);
        if (frames < 2) {
            return peak;
        }

        for (int channel = 0; channel < kOutputChannels; ++channel) {
            for (uint32_t frame = 0; frame + 1 < frames; ++frame) {
                const size_t current = static_cast<size_t>(frame) * kOutputChannels + channel;
                const size_t next = static_cast<size_t>(frame + 1) * kOutputChannels + channel;
                const size_t prev = frame > 0 ? current - kOutputChannels : current;
                const size_t after = frame + 2 < frames ? next + kOutputChannels : next;
                const double p0 = stereo_[prev];
                const double p1 = stereo_[current];
                const double p2 = stereo_[next];
                const double p3 = stereo_[after];
                for (double frac : kSoundEnhancerTruePeakFractions) {
                    peak = std::max(peak, std::abs(catmull_rom_sample(p0, p1, p2, p3, frac)));
                }
            }
        }
        return peak;
    }

    double apply_sound_enhancer(uint32_t frames, bool& limited) {
        // Post-mix laptop-speaker loudness: fixed makeup gain, then a fast
        // inter-sample safety envelope at -1 dBFS before the final limiter.
        // This deliberately leaves matrix, PEQ, trim, and routing math intact.
        limited = false;
        if (frames == 0) {
            return 1.0;
        }

        const double peak = estimated_true_peak_stereo(frames);
        double targetSafetyGain = 1.0;
        if (peak > 1e-12) {
            const double boostedPeak = peak * kSoundEnhancerMakeupGain;
            if (boostedPeak > kSoundEnhancerCeiling) {
                targetSafetyGain = kSoundEnhancerCeiling / boostedPeak;
                limited = true;
            }
        }

        const double alpha = targetSafetyGain < soundEnhancerSafetyGain_
            ? kSoundEnhancerAttackAlpha
            : kSoundEnhancerReleaseAlpha;
        const double smoothedSafetyGain = ((1.0 - alpha) * soundEnhancerSafetyGain_) + (alpha * targetSafetyGain);
        const double appliedSafetyGain = limited ? std::min(smoothedSafetyGain, targetSafetyGain) : smoothedSafetyGain;
        soundEnhancerSafetyGain_ = smoothedSafetyGain;

        double appliedGain = kSoundEnhancerMakeupGain * appliedSafetyGain;
        double previousGain = soundEnhancerAppliedGain_;
        if (!std::isfinite(previousGain) || previousGain <= 0.0) {
            previousGain = appliedGain;
        }
        const double startGain = std::min(previousGain, appliedGain);
        const uint32_t rampFrames = std::min(frames, kSoundEnhancerGainRampSamples);
        if (rampFrames > 1 && std::abs(appliedGain - startGain) > 1e-6) {
            const double step = (appliedGain - startGain) / static_cast<double>(rampFrames - 1);
            for (uint32_t frame = 0; frame < rampFrames; ++frame) {
                const double gain = startGain + (step * static_cast<double>(frame));
                const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
                stereo_[stereoIndex] *= gain;
                stereo_[stereoIndex + 1] *= gain;
            }
            for (uint32_t frame = rampFrames; frame < frames; ++frame) {
                const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
                stereo_[stereoIndex] *= appliedGain;
                stereo_[stereoIndex + 1] *= appliedGain;
            }
        } else {
            for (uint32_t frame = 0; frame < frames; ++frame) {
                const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
                stereo_[stereoIndex] *= appliedGain;
                stereo_[stereoIndex + 1] *= appliedGain;
            }
        }

        const double postPeak = estimated_true_peak_stereo(frames);
        if (postPeak > kSoundEnhancerCeiling) {
            const double emergencyGain = kSoundEnhancerCeiling / postPeak;
            for (uint32_t frame = 0; frame < frames; ++frame) {
                const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
                stereo_[stereoIndex] *= emergencyGain;
                stereo_[stereoIndex + 1] *= emergencyGain;
            }
            appliedGain *= emergencyGain;
            limited = true;
        }

        soundEnhancerAppliedGain_ = appliedGain;
        return appliedGain;
    }

    void activate_pending_peq_config() {
        auto published = std::atomic_load_explicit(&publishedPeqConfig_, std::memory_order_acquire);
        if (!published || published == peqActiveConfig_) {
            return;
        }
        peqTransitionConfig_ = peqActiveConfig_;
        peqTransitionState_ = peqActiveState_;
        peqActiveConfig_ = published;
        peqActiveState_ = PeqRuntimeState{};
        peqCrossfadeRemaining_ = kPeqCrossfadeSamples;
    }

    void apply_peq_routing(uint32_t frames) {
        if (frames == 0) {
            return;
        }
        activate_pending_peq_config();
        if ((!peqActiveConfig_ || peqActiveConfig_->bypassed()) && !peqTransitionConfig_) {
            return;
        }

        if (!peqTransitionConfig_) {
            apply_peq_config_to_buffer(*peqActiveConfig_, peqActiveState_, stereo_.data(), frames);
            return;
        }

        const size_t sampleCount = static_cast<size_t>(frames) * kOutputChannels;
        std::copy(stereo_.begin(), stereo_.begin() + sampleCount, peqOldStereo_.begin());
        apply_peq_config_to_buffer(*peqTransitionConfig_, peqTransitionState_, peqOldStereo_.data(), frames);
        apply_peq_config_to_buffer(*peqActiveConfig_, peqActiveState_, stereo_.data(), frames);

        const int fadeFrames = std::min<int>(static_cast<int>(frames), peqCrossfadeRemaining_);
        const int start = kPeqCrossfadeSamples - peqCrossfadeRemaining_;
        for (int frame = 0; frame < fadeFrames; ++frame) {
            const double t = static_cast<double>(start + frame + 1) / static_cast<double>(kPeqCrossfadeSamples);
            const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
            stereo_[stereoIndex] = peqOldStereo_[stereoIndex] * (1.0 - t) + stereo_[stereoIndex] * t;
            stereo_[stereoIndex + 1] = peqOldStereo_[stereoIndex + 1] * (1.0 - t) + stereo_[stereoIndex + 1] * t;
        }
        peqCrossfadeRemaining_ -= fadeFrames;
        if (peqCrossfadeRemaining_ <= 0) {
            peqTransitionConfig_.reset();
            peqTransitionState_ = PeqRuntimeState{};
        }
    }

    void apply_peq_config_to_buffer(
        const PeqConfig& config,
        PeqRuntimeState& state,
        double* stereo,
        uint32_t frames
    ) {
        if (config.global.active()) {
            apply_peq_cascade(config.global, state.global[0], stereo, 0, frames);
            apply_peq_cascade(config.global, state.global[1], stereo, 1, frames);
        }
        if (config.swapEnabled != 0) {
            for (uint32_t frame = 0; frame < frames; ++frame) {
                const size_t stereoIndex = static_cast<size_t>(frame) * kOutputChannels;
                std::swap(stereo[stereoIndex], stereo[stereoIndex + 1]);
            }
        }
        if (config.speakerEnabled != 0) {
            if (config.speakerLeft.active()) {
                apply_peq_cascade(config.speakerLeft, state.speakerLeft, stereo, 0, frames);
            }
            if (config.speakerRight.active()) {
                apply_peq_cascade(config.speakerRight, state.speakerRight, stereo, 1, frames);
            }
        }
    }

    void apply_peq_cascade(
        const PeqCascadeConfig& cascade,
        std::array<PeqBiquadState, kMaxPeqFilters>& state,
        double* stereo,
        int channel,
        uint32_t frames
    ) {
        if (!cascade.active()) {
            return;
        }
        if (std::abs(cascade.preampGain - 1.0) > 1e-12) {
            for (uint32_t frame = 0; frame < frames; ++frame) {
                stereo[static_cast<size_t>(frame) * kOutputChannels + channel] *= cascade.preampGain;
            }
        }
        for (int filter = 0; filter < cascade.count; ++filter) {
            const auto& coeff = cascade.filters[static_cast<size_t>(filter)];
            auto& filterState = state[static_cast<size_t>(filter)];
            double z1 = filterState.z1;
            double z2 = filterState.z2;
            for (uint32_t frame = 0; frame < frames; ++frame) {
                const size_t index = static_cast<size_t>(frame) * kOutputChannels + channel;
                const double input = stereo[index];
                double output = coeff.b0 * input + z1;
                z1 = coeff.b1 * input - coeff.a1 * output + z2;
                z2 = coeff.b2 * input - coeff.a2 * output;
                output = sanitize_denormal(output);
                stereo[index] = output;
            }
            filterState.z1 = sanitize_denormal(z1);
            filterState.z2 = sanitize_denormal(z2);
        }
    }

    void build_lfe_filter() {
        const double k = std::tan(kPi * kLfeLowpassCutoffHz / static_cast<double>(sampleRate_));
        for (size_t i = 0; i < kButterworthQ.size(); ++i) {
            const double q = kButterworthQ[i];
            const double norm = 1.0 / (1.0 + k / q + k * k);
            lfeSections_[i].b0 = k * k * norm;
            lfeSections_[i].b1 = 2.0 * lfeSections_[i].b0;
            lfeSections_[i].b2 = lfeSections_[i].b0;
            lfeSections_[i].a1 = 2.0 * (k * k - 1.0) * norm;
            lfeSections_[i].a2 = (1.0 - k / q + k * k) * norm;
        }
    }

    void prepare_input(const float* in, uint32_t frames, int inputChannels) {
        const int copyChannels = std::clamp(inputChannels, 0, kInputChannels);
        for (uint32_t frame = 0; frame < frames; ++frame) {
            float* row = &input_[static_cast<size_t>(frame) * kInputChannels];
            for (int ch = 0; ch < copyChannels; ++ch) {
                const float value = in[static_cast<size_t>(frame) * inputChannels + ch];
                row[ch] = std::isfinite(value) ? value : 0.0f;
            }
            for (int ch = copyChannels; ch < kInputChannels; ++ch) {
                row[ch] = 0.0f;
            }
        }
    }

    static void measure_levels(
        const float* data,
        uint32_t frames,
        std::array<float, kInputChannels>& levels,
        std::array<float, kInputChannels>& rms
    ) {
        levels.fill(0.0f);
        std::array<double, kInputChannels> squares{};
        squares.fill(0.0);
        if (frames == 0) {
            rms.fill(0.0f);
            return;
        }
        for (uint32_t frame = 0; frame < frames; ++frame) {
            const float* row = &data[static_cast<size_t>(frame) * kInputChannels];
            for (int ch = 0; ch < kInputChannels; ++ch) {
                const float value = row[ch];
                levels[ch] = std::max(levels[ch], std::abs(value));
                squares[ch] += static_cast<double>(value) * static_cast<double>(value);
            }
        }
        for (int ch = 0; ch < kInputChannels; ++ch) {
            rms[ch] = static_cast<float>(std::sqrt(squares[ch] / static_cast<double>(frames)));
        }
    }

    void channel_peaks(const float* field, uint32_t frames, std::array<float, kInputChannels>& peaks) const {
        peaks.fill(0.0f);
        for (uint32_t frame = 0; frame < frames; ++frame) {
            const float* row = &field[static_cast<size_t>(frame) * kInputChannels];
            for (int ch = 0; ch < kInputChannels; ++ch) {
                peaks[ch] = std::max(peaks[ch], std::abs(row[ch]));
            }
        }
    }

    static double dot_channel(const float* field, uint32_t frames, int a, int b) {
        double total = 0.0;
        for (uint32_t frame = 0; frame < frames; ++frame) {
            total += static_cast<double>(sample(field, frame, a)) * static_cast<double>(sample(field, frame, b));
        }
        return total;
    }

    static double energy_channel(const float* field, uint32_t frames, int ch) {
        return dot_channel(field, frames, ch, ch);
    }

    static float peak_channel(const float* field, uint32_t frames, int ch) {
        float peak = 0.0f;
        for (uint32_t frame = 0; frame < frames; ++frame) {
            peak = std::max(peak, std::abs(sample(field, frame, ch)));
        }
        return peak;
    }

    bool apply_channel_sanity(float* field, uint32_t frames, bool enabled) {
        if (!enabled || frames == 0) {
            return false;
        }
        std::array<float, kInputChannels> peaks{};
        channel_peaks(field, frames, peaks);
        if (peaks[0] <= kChannelSanityThreshold || peaks[1] <= kChannelSanityThreshold) {
            return false;
        }

        const double leftEnergy = std::max(energy_channel(field, frames, 0), 1e-12);
        const double rightEnergy = std::max(energy_channel(field, frames, 1), 1e-12);
        const double frontRms = std::max({
            std::sqrt(leftEnergy / static_cast<double>(frames)),
            std::sqrt(rightEnergy / static_cast<double>(frames)),
            static_cast<double>(kChannelSanityThreshold),
        });

        std::array<int, kInputChannels> duplicated{};
        int duplicateCount = 0;
        for (int ch = 2; ch < kInputChannels; ++ch) {
            if (peaks[ch] <= kChannelSanityThreshold) {
                continue;
            }
            const double channelEnergy = std::max(energy_channel(field, frames, ch), 1e-12);
            const double channelRms = std::sqrt(channelEnergy / static_cast<double>(frames));
            const double leftCorr = std::abs(dot_channel(field, frames, ch, 0)) / std::sqrt(channelEnergy * leftEnergy);
            const double rightCorr = std::abs(dot_channel(field, frames, ch, 1)) / std::sqrt(channelEnergy * rightEnergy);
            const double rmsRatio = channelRms / frontRms;
            if (std::max(leftCorr, rightCorr) >= kChannelSanityCorrelation && rmsRatio >= 0.35 && rmsRatio <= 1.65) {
                duplicated[ch] = 1;
                ++duplicateCount;
            }
        }

        if (duplicateCount < kChannelSanityMinDuplicates) {
            return false;
        }
        for (uint32_t frame = 0; frame < frames; ++frame) {
            for (int ch = 2; ch < kInputChannels; ++ch) {
                if (duplicated[ch]) {
                    sample(field, frame, ch) = 0.0f;
                }
            }
        }
        return true;
    }

    bool apply_surround_fill(float* field, uint32_t frames, bool enabled) {
        if (!enabled || frames == 0) {
            return false;
        }
        bool active = false;
        for (const auto pair : {std::array<int, 2>{4, 6}, std::array<int, 2>{5, 7}}) {
            const int sourceIndex = pair[0];
            const int targetIndex = pair[1];
            const bool sourceActive = peak_channel(field, frames, sourceIndex) > kSurroundFillThreshold;
            const bool targetSilent = peak_channel(field, frames, targetIndex) <= kSurroundFillThreshold;
            if (sourceActive && targetSilent) {
                for (uint32_t frame = 0; frame < frames; ++frame) {
                    const float source = sample(field, frame, sourceIndex);
                    sample(field, frame, targetIndex) = source * 0.5f;
                    sample(field, frame, sourceIndex) = source * 0.5f;
                }
                active = true;
            }
        }
        return active;
    }

    void build_sharur_916_bus(const float* source, uint32_t frames, int /*inputChannels*/, LayoutKind inputLayout) {
        const size_t sampleCount = static_cast<size_t>(frames) * kInputChannels;
        std::fill(renderBus_.begin(), renderBus_.begin() + sampleCount, 0.0f);
        if (inputLayout == LayoutKind::Sharur916) {
            std::copy(source, source + sampleCount, renderBus_.begin());
            return;
        }
        for (uint32_t frame = 0; frame < frames; ++frame) {
            sample(renderBus_.data(), frame, 0) = sample(source, frame, 0);
            sample(renderBus_.data(), frame, 1) = sample(source, frame, 1);
            sample(renderBus_.data(), frame, 2) = sample(source, frame, 2);
            sample(renderBus_.data(), frame, 3) = sample(source, frame, 3);
            sample(renderBus_.data(), frame, 4) = sample(source, frame, 4);
            sample(renderBus_.data(), frame, 5) = sample(source, frame, 5);
            sample(renderBus_.data(), frame, 8) = sample(source, frame, 6);
            sample(renderBus_.data(), frame, 9) = sample(source, frame, 7);
        }
    }

    bool generate_missing_sharur_916(
        float* bus,
        uint32_t frames,
        const float* source,
        int /*inputChannels*/,
        LayoutKind inputLayout,
        bool enabled
    ) {
        if (!enabled || frames == 0 || inputLayout == LayoutKind::Sharur916) {
            return false;
        }
        std::array<float, kInputChannels> peaks{};
        channel_peaks(source, frames, peaks);
        float maxBedPeak = 0.0f;
        for (int ch = 0; ch < kWindows71Channels; ++ch) {
            maxBedPeak = std::max(maxBedPeak, peaks[ch]);
        }
        if (maxBedPeak <= kUpmix916Threshold) {
            return false;
        }

        float* frontSide = scratch(0);
        float* sideSide = scratch(1);
        float* rearSide = scratch(2);
        float* frontAmbL = scratch(3);
        float* frontAmbR = scratch(4);
        float* sideAmbL = scratch(5);
        float* sideAmbR = scratch(6);
        float* rearAmbL = scratch(7);
        float* rearAmbR = scratch(8);
        float* flAir = scratch(9);
        float* frAir = scratch(10);
        float* fcAir = scratch(11);
        float* slAir = scratch(12);
        float* srAir = scratch(13);
        float* blAir = scratch(14);
        float* brAir = scratch(15);
        float* work = scratch(16);
        float* shaped = scratch(17);
        float* sideSrcL = scratch(18);
        float* sideSrcR = scratch(19);
        float* temp = scratch(20);

        const bool estimateSides =
            peak_channel(bus, frames, 8) <= kUpmix916Threshold &&
            peak_channel(bus, frames, 9) <= kUpmix916Threshold;
        for (uint32_t i = 0; i < frames; ++i) {
            const float fl = sample(bus, i, 0);
            const float fr = sample(bus, i, 1);
            const float bl = sample(bus, i, 4);
            const float br = sample(bus, i, 5);
            sideSrcL[i] = estimateSides ? (0.5f * bl + 0.25f * fl) : sample(bus, i, 8);
            sideSrcR[i] = estimateSides ? (0.5f * br + 0.25f * fr) : sample(bus, i, 9);
            frontSide[i] = 0.5f * (fl - fr);
            sideSide[i] = 0.5f * (sideSrcL[i] - sideSrcR[i]);
            rearSide[i] = 0.5f * (bl - br);
        }

        decorrelate(frontSide, frontAmbL, 0, frames);
        decorrelate(frontSide, frontAmbR, 1, frames);
        decorrelate(sideSide, sideAmbL, 2, frames);
        decorrelate(sideSide, sideAmbR, 3, frames);
        decorrelate(rearSide, rearAmbL, 4, frames);
        decorrelate(rearSide, rearAmbR, 5, frames);

        highpass_channel(bus, 0, temp, flAir, 0, kUpmixAirHighpassHz, frames);
        highpass_channel(bus, 1, temp, frAir, 1, kUpmixAirHighpassHz, frames);
        highpass_channel(bus, 2, temp, fcAir, 2, kUpmixAirHighpassHz, frames);
        highpass(sideSrcL, slAir, 3, kUpmixAirHighpassHz, frames);
        highpass(sideSrcR, srAir, 4, kUpmixAirHighpassHz, frames);
        highpass_channel(bus, 4, temp, blAir, 5, kUpmixAirHighpassHz, frames);
        highpass_channel(bus, 5, temp, brAir, 6, kUpmixAirHighpassHz, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.55f * sample(bus, i, 4) + 0.20f * sideSrcL[i] + 0.20f * rearAmbL[i] + 0.10f * sideAmbL[i];
        }
        shape_generated(work, shaped, 7, 0, 100.0, 14000.0, 0.0, frames);
        write_generated_channel(bus, shaped, 6, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.55f * sample(bus, i, 5) + 0.20f * sideSrcR[i] + 0.20f * rearAmbR[i] + 0.10f * sideAmbR[i];
        }
        shape_generated(work, shaped, 8, 1, 100.0, 14000.0, 0.0, frames);
        write_generated_channel(bus, shaped, 7, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.18f * flAir[i] + 0.06f * fcAir[i] + 0.30f * frontAmbL[i] + 0.08f * sideAmbL[i];
        }
        shape_generated(work, shaped, 9, 2, 200.0, 14000.0, 2.0, frames);
        write_generated_channel(bus, shaped, 10, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.18f * frAir[i] + 0.06f * fcAir[i] + 0.30f * frontAmbR[i] + 0.08f * sideAmbR[i];
        }
        shape_generated(work, shaped, 10, 3, 200.0, 14000.0, 2.0, frames);
        write_generated_channel(bus, shaped, 11, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.16f * slAir[i] + 0.08f * blAir[i] + 0.35f * sideAmbL[i] + 0.12f * rearAmbL[i];
        }
        shape_generated(work, shaped, 11, 4, 200.0, 13000.0, 1.0, frames);
        write_generated_channel(bus, shaped, 12, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.16f * srAir[i] + 0.08f * brAir[i] + 0.35f * sideAmbR[i] + 0.12f * rearAmbR[i];
        }
        shape_generated(work, shaped, 12, 5, 200.0, 13000.0, 1.0, frames);
        write_generated_channel(bus, shaped, 13, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.16f * blAir[i] + 0.08f * slAir[i] + 0.35f * rearAmbL[i] + 0.10f * sideAmbL[i];
        }
        shape_generated(work, shaped, 13, 6, 250.0, 12000.0, 0.5, frames);
        write_generated_channel(bus, shaped, 14, frames);

        for (uint32_t i = 0; i < frames; ++i) {
            work[i] = 0.16f * brAir[i] + 0.08f * srAir[i] + 0.35f * rearAmbR[i] + 0.10f * sideAmbR[i];
        }
        shape_generated(work, shaped, 14, 7, 250.0, 12000.0, 0.5, frames);
        write_generated_channel(bus, shaped, 15, frames);

        return true;
    }

    void decorrelate(const float* source, float* output, int slot, uint32_t frames) {
        std::copy(source, source + frames, output);
        const auto coeffs = kDecorCoeffs[static_cast<size_t>(slot) % kDecorCoeffs.size()];
        for (int stage = 0; stage < kDecorStages; ++stage) {
            const double gain = coeffs[static_cast<size_t>(stage)];
            double x1 = decorX1_[slot][stage];
            double y1 = decorY1_[slot][stage];
            for (uint32_t i = 0; i < frames; ++i) {
                const double sampleValue = static_cast<double>(output[i]);
                const double value = -gain * sampleValue + x1 + gain * y1;
                output[i] = static_cast<float>(value);
                x1 = sampleValue;
                y1 = value;
            }
            decorX1_[slot][stage] = x1;
            decorY1_[slot][stage] = y1;
        }
    }

    void highpass_channel(const float* bus, int channel, float* temp, float* output, int slot, double cutoffHz, uint32_t frames) {
        for (uint32_t i = 0; i < frames; ++i) {
            temp[i] = sample(bus, i, channel);
        }
        highpass(temp, output, slot, cutoffHz, frames);
    }

    void highpass(const float* source, float* output, int slot, double cutoffHz, uint32_t frames) {
        const double alpha = 1.0 / (1.0 + (2.0 * kPi * cutoffHz / static_cast<double>(sampleRate_)));
        double x1 = hpX1_[slot];
        double y1 = hpY1_[slot];
        for (uint32_t i = 0; i < frames; ++i) {
            const double sampleValue = static_cast<double>(source[i]);
            const double value = alpha * (y1 + sampleValue - x1);
            output[i] = static_cast<float>(value);
            x1 = sampleValue;
            y1 = value;
        }
        hpX1_[slot] = x1;
        hpY1_[slot] = y1;
    }

    void lowpass(const float* source, float* output, int slot, double cutoffHz, uint32_t frames) {
        const double alpha = 1.0 - std::exp(-2.0 * kPi * cutoffHz / static_cast<double>(sampleRate_));
        double y1 = lpY1_[slot];
        for (uint32_t i = 0; i < frames; ++i) {
            y1 += alpha * (static_cast<double>(source[i]) - y1);
            output[i] = static_cast<float>(y1);
        }
        lpY1_[slot] = y1;
    }

    void shape_generated(
        const float* source,
        float* output,
        int hpSlot,
        int lpSlot,
        double highpassHz,
        double lowpassHz,
        double shelfDb,
        uint32_t frames
    ) {
        highpass(source, output, hpSlot, highpassHz, frames);
        lowpass(output, output, lpSlot, lowpassHz, frames);
        const float shelfGain = static_cast<float>(db_to_linear(shelfDb));
        for (uint32_t i = 0; i < frames; ++i) {
            output[i] *= shelfGain;
        }
    }

    void write_generated_channel(float* bus, const float* source, int channel, uint32_t frames) {
        for (uint32_t i = 0; i < frames; ++i) {
            sample(bus, i, channel) = source[i] * kGeneratedChannelGain;
        }
    }

    void apply_sharur_processing(const float* input, uint32_t frames) {
        filter_lfe(input, frames);
        apply_dry_delay(input, frames);
        for (uint32_t frame = 0; frame < frames; ++frame) {
            processed_[static_cast<size_t>(frame) * kInputChannels + kLfeChannelIndex] = lfeScratch_[frame];
        }
    }

    void filter_lfe(const float* input, uint32_t frames) {
        for (uint32_t frame = 0; frame < frames; ++frame) {
            lfeScratch_[frame] = sample(input, frame, kLfeChannelIndex);
        }
        for (size_t section = 0; section < lfeSections_.size(); ++section) {
            const auto coeff = lfeSections_[section];
            double z1 = lfeState_[section][0];
            double z2 = lfeState_[section][1];
            for (uint32_t frame = 0; frame < frames; ++frame) {
                const double inputSample = static_cast<double>(lfeScratch_[frame]);
                const double outputSample = coeff.b0 * inputSample + z1;
                z1 = coeff.b1 * inputSample - coeff.a1 * outputSample + z2;
                z2 = coeff.b2 * inputSample - coeff.a2 * outputSample;
                lfeScratch_[frame] = static_cast<float>(outputSample);
            }
            lfeState_[section][0] = z1;
            lfeState_[section][1] = z2;
        }
    }

    void apply_dry_delay(const float* input, uint32_t frames) {
        const uint32_t delay = dryDelaySamples_;
        const uint32_t head = std::min<uint32_t>(frames, delay);
        for (uint32_t frame = 0; frame < head; ++frame) {
            for (int ch = 0; ch < kInputChannels; ++ch) {
                sample(processed_.data(), frame, ch) = dryDelay_[static_cast<size_t>(frame) * kInputChannels + ch];
            }
        }
        if (frames > delay) {
            for (uint32_t frame = delay; frame < frames; ++frame) {
                const uint32_t sourceFrame = frame - delay;
                for (int ch = 0; ch < kInputChannels; ++ch) {
                    sample(processed_.data(), frame, ch) = sample(input, sourceFrame, ch);
                }
            }
        }

        if (frames >= delay) {
            const uint32_t start = frames - delay;
            for (uint32_t frame = 0; frame < delay; ++frame) {
                for (int ch = 0; ch < kInputChannels; ++ch) {
                    dryDelay_[static_cast<size_t>(frame) * kInputChannels + ch] = sample(input, start + frame, ch);
                }
            }
        } else {
            const uint32_t keep = delay - frames;
            for (uint32_t frame = 0; frame < keep; ++frame) {
                for (int ch = 0; ch < kInputChannels; ++ch) {
                    dryDelay_[static_cast<size_t>(frame) * kInputChannels + ch] =
                        dryDelay_[static_cast<size_t>(frame + frames) * kInputChannels + ch];
                }
            }
            for (uint32_t frame = 0; frame < frames; ++frame) {
                for (int ch = 0; ch < kInputChannels; ++ch) {
                    dryDelay_[static_cast<size_t>(keep + frame) * kInputChannels + ch] = sample(input, frame, ch);
                }
            }
        }
    }

    void publish_static_config() {
        snapshotPreampDb_.store(preampDb_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotTrimLeftDb_.store(trimLeftDb_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotTrimRightDb_.store(trimRightDb_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotUserVolume_.store(userVolume_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotMasterVolume_.store(masterVolume_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotMasterMuted_.store(masterMuted_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotSurroundFillEnabled_.store(surroundFillEnabled_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotUpmix916Enabled_.store(upmix916Enabled_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotChannelSanityEnabled_.store(channelSanityEnabled_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotSoundEnhancerEnabled_.store(soundEnhancerEnabled_.load(std::memory_order_relaxed), std::memory_order_relaxed);
        snapshotSoundEnhancerGain_.store(1.0f, std::memory_order_relaxed);
    }

    void publish_zero_levels() {
        for (int i = 0; i < kInputChannels; ++i) {
            snapshotLevels_[i].store(0.0f, std::memory_order_relaxed);
            snapshotRms_[i].store(0.0f, std::memory_order_relaxed);
            snapshotRawLevels_[i].store(0.0f, std::memory_order_relaxed);
            snapshotRawRms_[i].store(0.0f, std::memory_order_relaxed);
        }
        snapshotLeftMeter_.store(0.0f, std::memory_order_relaxed);
        snapshotRightMeter_.store(0.0f, std::memory_order_relaxed);
    }

    void publish_snapshot(
        float leftMeter,
        float rightMeter,
        float preampDb,
        float trimLeftDb,
        float trimRightDb,
        float userVolume,
        float masterVolume,
        bool masterMuted,
        bool surroundFillEnabled,
        bool surroundFillActive,
        bool upmix916Enabled,
        bool upmix916Active,
        bool channelSanityEnabled,
        bool channelSanityActive,
        bool soundEnhancerEnabled,
        float soundEnhancerGain,
        bool clipping
    ) {
        for (int i = 0; i < kInputChannels; ++i) {
            snapshotLevels_[i].store(workLevels_[i], std::memory_order_relaxed);
            snapshotRms_[i].store(workRms_[i], std::memory_order_relaxed);
            snapshotRawLevels_[i].store(workRawLevels_[i], std::memory_order_relaxed);
            snapshotRawRms_[i].store(workRawRms_[i], std::memory_order_relaxed);
        }
        snapshotLeftMeter_.store(leftMeter, std::memory_order_relaxed);
        snapshotRightMeter_.store(rightMeter, std::memory_order_relaxed);
        snapshotPreampDb_.store(preampDb, std::memory_order_relaxed);
        snapshotTrimLeftDb_.store(trimLeftDb, std::memory_order_relaxed);
        snapshotTrimRightDb_.store(trimRightDb, std::memory_order_relaxed);
        snapshotLimiterGain_.store(static_cast<float>(limiterGain_), std::memory_order_relaxed);
        snapshotClipping_.store(clipping ? 1 : 0, std::memory_order_relaxed);
        snapshotUserVolume_.store(userVolume, std::memory_order_relaxed);
        snapshotMasterVolume_.store(masterVolume, std::memory_order_relaxed);
        snapshotMasterMuted_.store(masterMuted ? 1 : 0, std::memory_order_relaxed);
        snapshotSurroundFillEnabled_.store(surroundFillEnabled ? 1 : 0, std::memory_order_relaxed);
        snapshotSurroundFillActive_.store(surroundFillActive ? 1 : 0, std::memory_order_relaxed);
        snapshotUpmix916Enabled_.store(upmix916Enabled ? 1 : 0, std::memory_order_relaxed);
        snapshotUpmix916Active_.store(upmix916Active ? 1 : 0, std::memory_order_relaxed);
        snapshotChannelSanityEnabled_.store(channelSanityEnabled ? 1 : 0, std::memory_order_relaxed);
        snapshotChannelSanityActive_.store(channelSanityActive ? 1 : 0, std::memory_order_relaxed);
        snapshotSoundEnhancerEnabled_.store(soundEnhancerEnabled ? 1 : 0, std::memory_order_relaxed);
        snapshotSoundEnhancerGain_.store(soundEnhancerGain, std::memory_order_relaxed);
    }

    int capacityFrames_ = 0;
    std::vector<float> input_;
    std::vector<float> effective_;
    std::vector<float> renderBus_;
    std::vector<float> processed_;
    std::vector<double> stereo_;
    std::vector<double> peqOldStereo_;
    std::vector<float> lfeScratch_;
    std::vector<float> upmixScratch_;
    std::vector<float> dryDelay_;
    uint32_t sampleRate_ = 0;
    uint32_t dryDelaySamples_ = 0;
    std::array<LowpassSection, 2> lfeSections_{};
    std::array<std::array<double, 2>, 2> lfeState_{};
    std::array<std::array<double, kDecorStages>, 8> decorX1_{};
    std::array<std::array<double, kDecorStages>, 8> decorY1_{};
    std::array<double, kUpmixScratchChannels> hpX1_{};
    std::array<double, kUpmixScratchChannels> hpY1_{};
    std::array<double, kUpmixScratchChannels> lpY1_{};
    std::shared_ptr<const PeqConfig> publishedPeqConfig_;
    std::shared_ptr<const PeqConfig> peqActiveConfig_;
    std::shared_ptr<const PeqConfig> peqTransitionConfig_;
    PeqRuntimeState peqActiveState_{};
    PeqRuntimeState peqTransitionState_{};
    std::atomic<uint64_t> peqGeneration_{0};
    int peqCrossfadeRemaining_ = 0;

    std::array<float, kInputChannels> workLevels_{};
    std::array<float, kInputChannels> workRms_{};
    std::array<float, kInputChannels> workRawLevels_{};
    std::array<float, kInputChannels> workRawRms_{};

    std::atomic<float> preampDb_{-14.0f};
    std::atomic<float> preampGain_{static_cast<float>(db_to_linear(-14.0))};
    std::atomic<float> trimLeftDb_{0.0f};
    std::atomic<float> trimRightDb_{0.0f};
    std::atomic<float> trimLeftGain_{1.0f};
    std::atomic<float> trimRightGain_{1.0f};
    std::atomic<float> userVolume_{1.0f};
    std::atomic<float> masterVolume_{1.0f};
    std::atomic<int32_t> masterMuted_{0};
    std::atomic<int32_t> surroundFillEnabled_{0};
    std::atomic<int32_t> upmix916Enabled_{0};
    std::atomic<int32_t> channelSanityEnabled_{0};
    std::atomic<int32_t> soundEnhancerEnabled_{0};
    std::atomic<int32_t> soundEnhancerResetPending_{0};
    std::atomic<int32_t> monitorLayout_{0};
    std::atomic<int32_t> inputLayout_{0};
    double limiterGain_ = 1.0;
    double soundEnhancerSafetyGain_ = 1.0;
    double soundEnhancerAppliedGain_ = 1.0;

    std::array<std::atomic<float>, kInputChannels> snapshotLevels_{};
    std::array<std::atomic<float>, kInputChannels> snapshotRms_{};
    std::array<std::atomic<float>, kInputChannels> snapshotRawLevels_{};
    std::array<std::atomic<float>, kInputChannels> snapshotRawRms_{};
    std::atomic<float> snapshotLeftMeter_{0.0f};
    std::atomic<float> snapshotRightMeter_{0.0f};
    std::atomic<float> snapshotPreampDb_{-14.0f};
    std::atomic<float> snapshotTrimLeftDb_{0.0f};
    std::atomic<float> snapshotTrimRightDb_{0.0f};
    std::atomic<float> snapshotLimiterGain_{1.0f};
    std::atomic<int32_t> snapshotClipping_{0};
    std::atomic<float> snapshotUserVolume_{1.0f};
    std::atomic<float> snapshotMasterVolume_{1.0f};
    std::atomic<int32_t> snapshotMasterMuted_{0};
    std::atomic<int32_t> snapshotSurroundFillEnabled_{0};
    std::atomic<int32_t> snapshotSurroundFillActive_{0};
    std::atomic<int32_t> snapshotUpmix916Enabled_{0};
    std::atomic<int32_t> snapshotUpmix916Active_{0};
    std::atomic<int32_t> snapshotChannelSanityEnabled_{0};
    std::atomic<int32_t> snapshotChannelSanityActive_{0};
    std::atomic<int32_t> snapshotSoundEnhancerEnabled_{0};
    std::atomic<float> snapshotSoundEnhancerGain_{1.0f};
};

class NativeEngine {
public:
    NativeEngine() = default;
    ~NativeEngine() {
        stop();
    }

    bool start(
        const char* inputEndpointId,
        const char* inputName,
        const char* outputEndpointId,
        const char* outputName,
        const char* profileName,
        uint32_t blockSize,
        uint32_t sampleRate
    ) {
        std::lock_guard<std::mutex> guard(controlMutex_);
        stop_locked();
        lastError_.clear();
        const uint32_t safeBlockSize = std::max<uint32_t>(64, std::min<uint32_t>(blockSize, 4096));
        sampleRate_ = normalize_sample_rate(sampleRate);
        dsp_.set_sample_rate(sampleRate_);
        dsp_.reserve(static_cast<int>(safeBlockSize) * 8);
        dsp_.reset_runtime_state();
        prepare_mmcss_api();

        ma_backend backends[] = {ma_backend_wasapi};
        ma_context_config contextConfig = ma_context_config_init();
        ma_result result = ma_context_init(backends, 1, &contextConfig, &context_);
        if (result != MA_SUCCESS) {
            lastError_ = "WASAPI context init failed: " + std::to_string(result);
            return false;
        }
        contextReady_ = true;

        ma_device_info* playbackInfos = nullptr;
        ma_uint32 playbackCount = 0;
        ma_device_info* captureInfos = nullptr;
        ma_uint32 captureCount = 0;
        result = ma_context_get_devices(&context_, &playbackInfos, &playbackCount, &captureInfos, &captureCount);
        if (result != MA_SUCCESS) {
            lastError_ = "WASAPI device enumeration failed: " + std::to_string(result);
            stop_locked();
            return false;
        }

        const std::string requestedInputEndpoint = inputEndpointId ? inputEndpointId : "";
        const std::string requestedOutputEndpoint = outputEndpointId ? outputEndpointId : "";
        const std::string requestedInputName = inputName ? inputName : "";
        const std::string requestedOutputName = outputName ? outputName : "";
        const DeviceSelection captureSelection = select_device(
            captureInfos,
            captureCount,
            requestedInputEndpoint,
            requestedInputName
        );
        const DeviceSelection playbackSelection = select_device(
            playbackInfos,
            playbackCount,
            requestedOutputEndpoint,
            requestedOutputName
        );
        ma_device_info* capture = captureSelection.info;
        ma_device_info* playback = playbackSelection.info;
        if (capture == nullptr) {
            if (captureSelection.ambiguous) {
                lastError_ = "Ambiguous WASAPI input device name in native backend; endpoint identity is required";
            } else if (captureSelection.endpointRequested) {
                lastError_ = "Unable to match WASAPI input endpoint identity in native backend";
            } else {
                lastError_ = "Unable to match WASAPI input device in native backend";
            }
            stop_locked();
            return false;
        }
        if (playback == nullptr) {
            if (playbackSelection.ambiguous) {
                lastError_ = "Ambiguous WASAPI output device name in native backend; endpoint identity is required";
            } else if (playbackSelection.endpointRequested) {
                lastError_ = "Unable to match WASAPI output endpoint identity in native backend";
            } else {
                lastError_ = "Unable to match WASAPI output device in native backend";
            }
            stop_locked();
            return false;
        }

        captureId_ = capture->id;
        playbackId_ = playback->id;
        inputName_ = capture->name;
        outputName_ = playback->name;
        profileName_ = profileName && *profileName ? profileName : "normal";
        const bool ultraProfile = ascii_lower(profileName_) == "ultra";
        blockSize_ = safeBlockSize;

        ma_device_config config = ma_device_config_init(ma_device_type_duplex);
        config.sampleRate = sampleRate_;
        config.periodSizeInFrames = safeBlockSize;
        config.periods = 3;
        config.performanceProfile = ma_performance_profile_low_latency;
        config.noPreSilencedOutputBuffer = ultraProfile ? MA_TRUE : MA_FALSE;
        config.noClip = ultraProfile ? MA_TRUE : MA_FALSE;
        config.dataCallback = &NativeEngine::data_callback;
        config.notificationCallback = &NativeEngine::notification_callback;
        config.pUserData = this;
        config.capture.pDeviceID = &captureId_;
        config.capture.format = ma_format_f32;
        config.capture.channels = kInputChannels;
        config.capture.shareMode = ma_share_mode_shared;
        config.playback.pDeviceID = &playbackId_;
        config.playback.format = ma_format_f32;
        config.playback.channels = kOutputChannels;
        config.playback.shareMode = ma_share_mode_shared;
        if (ultraProfile) {
            config.wasapi.usage = ma_wasapi_usage_pro_audio;
            config.wasapi.noAutoConvertSRC = MA_TRUE;
        }

        result = ma_device_init(&context_, &config, &device_);
        if (result != MA_SUCCESS) {
            lastError_ = "WASAPI stream init failed: " + std::to_string(result);
            stop_locked();
            return false;
        }
        deviceReady_ = true;

        dspErrorCount_.store(0, std::memory_order_relaxed);
        callbackStatusCount_.store(0, std::memory_order_relaxed);
        callbackInvocationCount_.store(0, std::memory_order_relaxed);
        processedFrameCount_.store(0, std::memory_order_relaxed);
        mmcssRegistered_.store(0, std::memory_order_relaxed);
        mmcssAttempted_.store(0, std::memory_order_relaxed);
        deviceNotificationType_.store(-1, std::memory_order_relaxed);
        cpuLoad_.store(0.0f, std::memory_order_relaxed);

        result = ma_device_start(&device_);
        if (result != MA_SUCCESS) {
            lastError_ = "WASAPI stream start failed: " + std::to_string(result);
            stop_locked();
            return false;
        }

        running_.store(1, std::memory_order_release);
        route_ = inputName_ + " (Windows WASAPI/C++) -> " + outputName_ + " (Windows WASAPI/C++)";
        status_ = "Running (C++ " + profileName_ + ")";
        return true;
    }

    void stop() {
        std::lock_guard<std::mutex> guard(controlMutex_);
        stop_locked();
    }

    void snapshot(NativeEngineSnapshot& out) {
        std::memset(&out, 0, sizeof(out));
        out.running = running_.load(std::memory_order_acquire);
        out.inputChannels = out.running ? kInputChannels : 0;
        out.callbackStatusCount = callbackStatusCount_.load(std::memory_order_relaxed);
        out.dspErrorCount = dspErrorCount_.load(std::memory_order_relaxed);
        out.callbackInvocationCount = callbackInvocationCount_.load(std::memory_order_relaxed);
        out.processedFrameCount = processedFrameCount_.load(std::memory_order_relaxed);
        out.mmcssRegistered = mmcssRegistered_.load(std::memory_order_relaxed);
        out.cpuLoad = cpuLoad_.load(std::memory_order_relaxed);
        out.inputLatency = static_cast<float>(blockSize_) / static_cast<float>(sampleRate_);
        out.outputLatency = static_cast<float>(blockSize_) / static_cast<float>(sampleRate_);
        out.hasLatency = blockSize_ > 0 ? 1 : 0;
        {
            std::lock_guard<std::mutex> guard(controlMutex_);
            copy_text(out.status, status_);
            copy_text(out.route, route_);
            copy_text(out.streamProfile, profileName_);
        }
        const int32_t notificationType = deviceNotificationType_.load(std::memory_order_relaxed);
        if (notificationType >= 0) {
            copy_text(out.callbackStatus, device_notification_text(static_cast<ma_device_notification_type>(notificationType)));
        } else {
            std::lock_guard<std::mutex> guard(controlMutex_);
            copy_text(out.callbackStatus, callbackStatus_);
        }
        dsp_.snapshot(out.dsp);
    }

    const std::string& last_error() const {
        return lastError_;
    }

    DownmixDsp& dsp() {
        return dsp_;
    }

    void set_sample_rate(uint32_t sampleRate) {
        std::lock_guard<std::mutex> guard(controlMutex_);
        if (running_.load(std::memory_order_acquire)) {
            return;
        }
        sampleRate_ = normalize_sample_rate(sampleRate);
        dsp_.set_sample_rate(sampleRate_);
    }

private:
    static void data_callback(ma_device* device, void* output, const void* input, ma_uint32 frameCount) {
        auto* self = static_cast<NativeEngine*>(device->pUserData);
        if (self == nullptr) {
            return;
        }
        if (self->mmcssAttempted_.exchange(1, std::memory_order_relaxed) == 0) {
            if (register_current_thread_mmcss()) {
                self->mmcssRegistered_.store(1, std::memory_order_relaxed);
            }
        }
        self->callbackInvocationCount_.fetch_add(1, std::memory_order_relaxed);
        self->processedFrameCount_.fetch_add(frameCount, std::memory_order_relaxed);
        auto startTime = std::chrono::steady_clock::now();
        const bool ok = self->dsp_.process(
            static_cast<const float*>(input),
            frameCount,
            kInputChannels,
            static_cast<float*>(output)
        );
        if (!ok) {
            self->dspErrorCount_.fetch_add(1, std::memory_order_relaxed);
        }
        auto endTime = std::chrono::steady_clock::now();
        const double elapsed = std::chrono::duration<double>(endTime - startTime).count();
        const double budget = static_cast<double>(frameCount) / static_cast<double>(self->sampleRate_);
        if (budget > 0.0) {
            self->cpuLoad_.store(static_cast<float>(elapsed / budget), std::memory_order_relaxed);
        }
    }

    static void notification_callback(const ma_device_notification* notification) {
        if (notification == nullptr || notification->pDevice == nullptr) {
            return;
        }
        auto* self = static_cast<NativeEngine*>(notification->pDevice->pUserData);
        if (self == nullptr) {
            return;
        }
        self->deviceNotificationType_.store(static_cast<int32_t>(notification->type), std::memory_order_relaxed);
        if (notification->type != ma_device_notification_type_started) {
            self->callbackStatusCount_.fetch_add(1, std::memory_order_relaxed);
        }
        if (
            notification->type == ma_device_notification_type_stopped ||
            notification->type == ma_device_notification_type_interruption_began
        ) {
            self->running_.store(0, std::memory_order_release);
        }
    }

    void stop_locked() {
        running_.store(0, std::memory_order_release);
        if (deviceReady_) {
            ma_device_stop(&device_);
            ma_device_uninit(&device_);
            deviceReady_ = false;
        }
        if (contextReady_) {
            ma_context_uninit(&context_);
            contextReady_ = false;
        }
        if (status_.empty() || status_.find("Running") != std::string::npos) {
            status_ = "Stopped";
        }
        route_ = "No route";
    }

    std::mutex controlMutex_;
    ma_context context_{};
    ma_device device_{};
    ma_device_id captureId_{};
    ma_device_id playbackId_{};
    bool contextReady_ = false;
    bool deviceReady_ = false;
    uint32_t blockSize_ = 0;
    uint32_t sampleRate_ = static_cast<uint32_t>(kSampleRate);
    std::string inputName_;
    std::string outputName_;
    std::string profileName_ = "normal";
    std::string route_ = "No route";
    std::string status_ = "Stopped";
    std::string callbackStatus_;
    std::string lastError_;
    DownmixDsp dsp_;
    std::atomic<int32_t> running_{0};
    std::atomic<int32_t> dspErrorCount_{0};
    std::atomic<int32_t> callbackStatusCount_{0};
    std::atomic<uint64_t> callbackInvocationCount_{0};
    std::atomic<uint64_t> processedFrameCount_{0};
    std::atomic<int32_t> mmcssRegistered_{0};
    std::atomic<int32_t> mmcssAttempted_{0};
    std::atomic<int32_t> deviceNotificationType_{-1};
    std::atomic<float> cpuLoad_{0.0f};
};

}  // namespace

extern "C" {

__declspec(dllexport) NativeEngine* downmix_native_create() {
    try {
        return new NativeEngine();
    } catch (...) {
        return nullptr;
    }
}

__declspec(dllexport) void downmix_native_destroy(NativeEngine* engine) {
    delete engine;
}

__declspec(dllexport) int32_t downmix_native_start(
    NativeEngine* engine,
    const char* inputName,
    const char* outputName,
    const char* profileName,
    uint32_t blockSize,
    uint32_t sampleRate
) {
    if (engine == nullptr) {
        return 0;
    }
    return engine->start("", inputName, "", outputName, profileName, blockSize, sampleRate) ? 1 : 0;
}

__declspec(dllexport) int32_t downmix_native_start_endpoints(
    NativeEngine* engine,
    const char* inputEndpointId,
    const char* inputName,
    const char* outputEndpointId,
    const char* outputName,
    const char* profileName,
    uint32_t blockSize,
    uint32_t sampleRate
) {
    if (engine == nullptr) {
        return 0;
    }
    return engine->start(
        inputEndpointId,
        inputName,
        outputEndpointId,
        outputName,
        profileName,
        blockSize,
        sampleRate
    ) ? 1 : 0;
}

__declspec(dllexport) int32_t downmix_native_enumerate_devices(
    NativeDeviceDescriptor* devices,
    uint32_t capacity,
    uint32_t* count
) {
    if (count == nullptr) {
        return 0;
    }
    *count = 0;

    ma_backend backends[] = {ma_backend_wasapi};
    ma_context context{};
    ma_context_config contextConfig = ma_context_config_init();
    ma_result result = ma_context_init(backends, 1, &contextConfig, &context);
    if (result != MA_SUCCESS) {
        return 0;
    }

    ma_device_info* playbackInfos = nullptr;
    ma_uint32 playbackCount = 0;
    ma_device_info* captureInfos = nullptr;
    ma_uint32 captureCount = 0;
    result = ma_context_get_devices(&context, &playbackInfos, &playbackCount, &captureInfos, &captureCount);
    if (result != MA_SUCCESS) {
        ma_context_uninit(&context);
        return 0;
    }

    const uint32_t total = static_cast<uint32_t>(playbackCount + captureCount);
    if (devices == nullptr || capacity == 0) {
        *count = total;
        ma_context_uninit(&context);
        return 1;
    }

    uint32_t written = 0;
    for (ma_uint32 i = 0; i < playbackCount && written < capacity; ++i) {
        fill_device_descriptor(devices[written], playbackInfos[i], 0);
        ++written;
    }
    for (ma_uint32 i = 0; i < captureCount && written < capacity; ++i) {
        fill_device_descriptor(devices[written], captureInfos[i], 1);
        ++written;
    }
    *count = written;
    ma_context_uninit(&context);
    return written == total ? 1 : 0;
}

__declspec(dllexport) void downmix_native_stop(NativeEngine* engine) {
    if (engine != nullptr) {
        engine->stop();
    }
}

__declspec(dllexport) void downmix_native_snapshot(NativeEngine* engine, NativeEngineSnapshot* out) {
    if (out == nullptr) {
        return;
    }
    if (engine == nullptr) {
        std::memset(out, 0, sizeof(NativeEngineSnapshot));
        copy_text(out->status, "Native backend unavailable");
        copy_text(out->route, "No route");
        copy_text(out->streamProfile, "normal");
        return;
    }
    engine->snapshot(*out);
}

__declspec(dllexport) void downmix_native_last_error(NativeEngine* engine, char* out, uint32_t outSize) {
    if (out == nullptr || outSize == 0) {
        return;
    }
    std::memset(out, 0, outSize);
    if (engine == nullptr) {
        std::strncpy(out, "Native backend unavailable", outSize - 1);
        return;
    }
    std::strncpy(out, engine->last_error().c_str(), outSize - 1);
}

__declspec(dllexport) void downmix_native_set_preamp_db(NativeEngine* engine, float value) {
    if (engine != nullptr) {
        engine->dsp().set_preamp_db(value);
    }
}

__declspec(dllexport) void downmix_native_set_user_volume(NativeEngine* engine, float value) {
    if (engine != nullptr) {
        engine->dsp().set_user_volume(value);
    }
}

__declspec(dllexport) void downmix_native_set_sample_rate(NativeEngine* engine, uint32_t sampleRate) {
    if (engine != nullptr) {
        engine->set_sample_rate(sampleRate);
    }
}

__declspec(dllexport) void downmix_native_set_channel_trim_db(NativeEngine* engine, float leftDb, float rightDb) {
    if (engine != nullptr) {
        engine->dsp().set_channel_trim_db(leftDb, rightDb);
    }
}

__declspec(dllexport) void downmix_native_set_master_volume(NativeEngine* engine, float scalar, int32_t muted) {
    if (engine != nullptr) {
        engine->dsp().set_master_volume(scalar, muted != 0);
    }
}

__declspec(dllexport) void downmix_native_set_surround_fill_enabled(NativeEngine* engine, int32_t enabled) {
    if (engine != nullptr) {
        engine->dsp().set_surround_fill_enabled(enabled != 0);
    }
}

__declspec(dllexport) void downmix_native_set_upmix_916_enabled(NativeEngine* engine, int32_t enabled) {
    if (engine != nullptr) {
        engine->dsp().set_upmix_916_enabled(enabled != 0);
    }
}

__declspec(dllexport) void downmix_native_set_channel_sanity_enabled(NativeEngine* engine, int32_t enabled) {
    if (engine != nullptr) {
        engine->dsp().set_channel_sanity_enabled(enabled != 0);
    }
}

__declspec(dllexport) void downmix_native_set_sound_enhancer_enabled(NativeEngine* engine, int32_t enabled) {
    if (engine != nullptr) {
        engine->dsp().set_sound_enhancer_enabled(enabled != 0);
    }
}

__declspec(dllexport) void downmix_native_set_monitor_layout(NativeEngine* engine, int32_t layout) {
    if (engine != nullptr) {
        engine->dsp().set_monitor_layout(layout);
    }
}

__declspec(dllexport) void downmix_native_set_input_layout(NativeEngine* engine, int32_t layout) {
    if (engine != nullptr) {
        engine->dsp().set_input_layout(layout);
    }
}

__declspec(dllexport) void downmix_native_set_peq_config(
    NativeEngine* engine,
    int32_t globalEnabled,
    const double* globalCoeffs,
    uint32_t globalCount,
    double globalPreampDb,
    int32_t speakerEnabled,
    const double* speakerLeftCoeffs,
    uint32_t speakerLeftCount,
    double speakerLeftPreampDb,
    const double* speakerRightCoeffs,
    uint32_t speakerRightCount,
    double speakerRightPreampDb,
    int32_t swapEnabled
) {
    if (engine != nullptr) {
        engine->dsp().set_peq_config(
            globalEnabled,
            globalCoeffs,
            globalCount,
            globalPreampDb,
            speakerEnabled,
            speakerLeftCoeffs,
            speakerLeftCount,
            speakerLeftPreampDb,
            speakerRightCoeffs,
            speakerRightCount,
            speakerRightPreampDb,
            swapEnabled
        );
    }
}

__declspec(dllexport) void downmix_native_reset_runtime_state(NativeEngine* engine) {
    if (engine != nullptr) {
        engine->dsp().reset_runtime_state();
    }
}

__declspec(dllexport) int32_t downmix_native_process_float32(
    NativeEngine* engine,
    const float* input,
    uint32_t frames,
    int32_t inputChannels,
    float* output
) {
    if (engine == nullptr || input == nullptr || output == nullptr || inputChannels <= 0) {
        return 0;
    }
    return engine->dsp().process(input, frames, inputChannels, output) ? 1 : 0;
}

__declspec(dllexport) const char* downmix_native_backend_name() {
    return "C++ WASAPI/miniaudio downmix backend";
}

}  // extern "C"
