#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <initguid.h>
#include <audioclient.h>
#include <fcntl.h>
#include <io.h>
#include <mmdeviceapi.h>
#include <mmsystem.h>
#include <objidl.h>
#include <propidl.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace {

// MinGW's Windows headers expose ActivateAudioInterfaceAsync but do not yet
// declare the process-loopback activation payload from recent Windows SDKs.
// Keep the ABI declarations local so this helper remains buildable with the
// toolchain used by this project.
enum class ProcessActivationType : uint32_t {
  kDefault = 0,
  kProcessLoopback = 1,
};

enum class ProcessLoopbackMode : uint32_t {
  kIncludeTargetProcessTree = 0,
  kExcludeTargetProcessTree = 1,
};

struct ProcessLoopbackParameters {
  DWORD targetProcessId;
  ProcessLoopbackMode mode;
};

struct AudioClientActivationParameters {
  ProcessActivationType activationType;
  ProcessLoopbackParameters processLoopbackParameters;
};

constexpr wchar_t kProcessLoopbackDevice[] = L"VAD\\Process_Loopback";
constexpr uint32_t kSampleRate = 48000;
constexpr uint16_t kChannels = 2;
constexpr uint16_t kSampleFormatFloat32 = 1;
constexpr uint32_t kFramesPerBlock = kSampleRate / 100;
constexpr uint32_t kMaximumBufferedFrames = kSampleRate / 10;

#pragma pack(push, 1)
struct StreamHeader {
  char magic[4];
  uint32_t sampleRate;
  uint16_t channels;
  uint16_t sampleFormat;
};
#pragma pack(pop)

static_assert(sizeof(StreamHeader) == 12);

void printError(const char* operation, HRESULT result) {
  std::fprintf(stderr, "%s failed: HRESULT 0x%08lx\n", operation,
               static_cast<unsigned long>(result));
}

bool writeAll(const void* data, size_t size) {
  const auto* cursor = static_cast<const uint8_t*>(data);
  while (size > 0) {
    const size_t written = std::fwrite(cursor, 1, size, stdout);
    if (written == 0) return false;
    cursor += written;
    size -= written;
  }
  return true;
}

class ActivationHandler final : public IActivateAudioInterfaceCompletionHandler {
 public:
  ActivationHandler() : completed_(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {}

  ~ActivationHandler() {
    if (audioClient_ != nullptr) audioClient_->Release();
    if (completed_ != nullptr) CloseHandle(completed_);
  }

  bool valid() const { return completed_ != nullptr; }

  HRESULT wait(IAudioClient** audioClient) {
    if (WaitForSingleObject(completed_, 5000) != WAIT_OBJECT_0) {
      return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    }
    if (FAILED(result_)) return result_;
    if (audioClient_ == nullptr) return E_UNEXPECTED;
    audioClient_->AddRef();
    *audioClient = audioClient_;
    return S_OK;
  }

  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** object) override {
    if (object == nullptr) return E_POINTER;
    *object = nullptr;
    if (IsEqualIID(iid, IID_IUnknown) ||
        IsEqualIID(iid, IID_IActivateAudioInterfaceCompletionHandler) ||
        IsEqualIID(iid, IID_IAgileObject)) {
      *object = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
      AddRef();
      return S_OK;
    }
    return E_NOINTERFACE;
  }

  ULONG STDMETHODCALLTYPE AddRef() override {
    return static_cast<ULONG>(++references_);
  }

  ULONG STDMETHODCALLTYPE Release() override {
    const ULONG remaining = static_cast<ULONG>(--references_);
    if (remaining == 0) delete this;
    return remaining;
  }

  HRESULT STDMETHODCALLTYPE ActivateCompleted(
      IActivateAudioInterfaceAsyncOperation* operation) override {
    HRESULT activationResult = E_UNEXPECTED;
    IUnknown* activated = nullptr;
    result_ = operation->GetActivateResult(&activationResult, &activated);
    if (SUCCEEDED(result_)) result_ = activationResult;
    if (SUCCEEDED(result_) && activated != nullptr) {
      result_ = activated->QueryInterface(
          IID_IAudioClient, reinterpret_cast<void**>(&audioClient_));
    }
    if (activated != nullptr) activated->Release();
    SetEvent(completed_);
    return S_OK;
  }

 private:
  std::atomic<ULONG> references_{1};
  HANDLE completed_ = nullptr;
  HRESULT result_ = E_PENDING;
  IAudioClient* audioClient_ = nullptr;
};

HRESULT activateProcessLoopback(DWORD processId, ProcessLoopbackMode mode,
                                IAudioClient** audioClient) {
  AudioClientActivationParameters activation = {};
  activation.activationType = ProcessActivationType::kProcessLoopback;
  activation.processLoopbackParameters.targetProcessId = processId;
  activation.processLoopbackParameters.mode = mode;

  PROPVARIANT parameters = {};
  parameters.vt = VT_BLOB;
  parameters.blob.cbSize = sizeof(activation);
  parameters.blob.pBlobData = reinterpret_cast<BYTE*>(&activation);

  auto* handler = new ActivationHandler();
  if (!handler->valid()) {
    handler->Release();
    return HRESULT_FROM_WIN32(GetLastError());
  }

  IActivateAudioInterfaceAsyncOperation* operation = nullptr;
  HRESULT result = ActivateAudioInterfaceAsync(
      kProcessLoopbackDevice, IID_IAudioClient, &parameters, handler,
      &operation);
  if (SUCCEEDED(result)) result = handler->wait(audioClient);
  // The MinGW projection of the async-operation Release call blocks on some
  // Windows 11 builds after successful process-loopback activation. The
  // helper owns a single activation for its process lifetime, so intentionally
  // retain this tiny COM object and let process teardown reclaim it.
  (void)operation;
  handler->Release();
  return result;
}

int capture(DWORD processId, ProcessLoopbackMode mode) {
  IAudioClient* audioClient = nullptr;
  HRESULT result = activateProcessLoopback(processId, mode, &audioClient);
  if (FAILED(result)) {
    printError("ActivateAudioInterfaceAsync", result);
    return 3;
  }

  WAVEFORMATEX format = {};
  format.wFormatTag = WAVE_FORMAT_PCM;
  format.nChannels = kChannels;
  format.nSamplesPerSec = kSampleRate;
  format.wBitsPerSample = 16;
  format.nBlockAlign = format.nChannels * format.wBitsPerSample / 8;
  format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;

  const DWORD flags = AUDCLNT_STREAMFLAGS_LOOPBACK |
                      AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
                      AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
  result = audioClient->Initialize(AUDCLNT_SHAREMODE_SHARED, flags, 1000000, 0,
                                   &format, nullptr);
  if (FAILED(result)) {
    printError("IAudioClient::Initialize", result);
    return 4;
  }

  IAudioCaptureClient* captureClient = nullptr;
  result = audioClient->GetService(
      IID_IAudioCaptureClient, reinterpret_cast<void**>(&captureClient));
  if (FAILED(result)) {
    printError("IAudioClient::GetService", result);
    return 7;
  }

  result = audioClient->Start();
  if (FAILED(result)) {
    printError("IAudioClient::Start", result);
    return 8;
  }

  const StreamHeader header = {{'U', 'P', 'C', 'M'}, kSampleRate,
                               kChannels, kSampleFormatFloat32};
  if (!writeAll(&header, sizeof(header))) {
    audioClient->Stop();
    return 9;
  }

  std::vector<float> pending;
  size_t pendingOffset = 0;
  std::array<float, kFramesPerBlock * kChannels> output = {};
  auto nextOutput =
      std::chrono::steady_clock::now() + std::chrono::milliseconds(10);
  bool running = true;
  while (running) {
    Sleep(1);

    UINT32 frames = 0;
    while (running) {
      result = captureClient->GetNextPacketSize(&frames);
      if (FAILED(result)) {
        printError("IAudioCaptureClient::GetNextPacketSize", result);
        running = false;
        break;
      }
      if (frames == 0) break;

      BYTE* data = nullptr;
      DWORD captureFlags = 0;
      UINT64 devicePosition = 0;
      UINT64 qpcPosition = 0;
      result = captureClient->GetBuffer(&data, &frames, &captureFlags,
                                        &devicePosition, &qpcPosition);
      if (FAILED(result)) {
        running = false;
        break;
      }

      const size_t sampleCount = static_cast<size_t>(frames) * kChannels;
      if ((captureFlags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) != 0) {
        pending.clear();
        pendingOffset = 0;
      }
      if ((captureFlags & AUDCLNT_BUFFERFLAGS_SILENT) != 0) {
        pending.insert(pending.end(), sampleCount, 0.0f);
      } else {
        const auto* input = reinterpret_cast<const int16_t*>(data);
        pending.reserve(pending.size() + sampleCount);
        for (size_t index = 0; index < sampleCount; ++index) {
          pending.push_back(static_cast<float>(input[index]) / 32768.0f);
        }
      }
      result = captureClient->ReleaseBuffer(frames);
      if (FAILED(result)) {
        printError("IAudioCaptureClient::ReleaseBuffer", result);
        running = false;
        break;
      }
    }

    size_t availableFrames =
        (pending.size() - pendingOffset) / kChannels;
    if (availableFrames > kMaximumBufferedFrames) {
      const size_t droppedFrames = availableFrames - kMaximumBufferedFrames;
      pendingOffset += droppedFrames * kChannels;
      availableFrames = kMaximumBufferedFrames;
    }
    if (pendingOffset > kFramesPerBlock * kChannels * 4) {
      pending.erase(pending.begin(), pending.begin() + pendingOffset);
      pendingOffset = 0;
    }

    const auto now = std::chrono::steady_clock::now();
    if (now >= nextOutput) {
      output.fill(0.0f);
      const size_t copiedFrames =
          std::min<size_t>(availableFrames, kFramesPerBlock);
      const size_t copiedSamples = copiedFrames * kChannels;
      if (copiedSamples > 0) {
        std::copy_n(pending.data() + pendingOffset, copiedSamples,
                    output.data());
      }
      pendingOffset += copiedSamples;
      running = writeAll(output.data(), output.size() * sizeof(float));

      if (now - nextOutput > std::chrono::milliseconds(50)) {
        nextOutput = now + std::chrono::milliseconds(10);
      } else {
        nextOutput += std::chrono::milliseconds(10);
      }
    }
  }

  audioClient->Stop();
  return running ? 0 : 10;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3 ||
      (std::strcmp(argv[1], "--include-pid") != 0 &&
       std::strcmp(argv[1], "--exclude-pid") != 0)) {
    std::fprintf(stderr,
                 "usage: wasapi_process_loopback "
                 "<--include-pid|--exclude-pid> <pid>\n");
    return 2;
  }

  const unsigned long parsed = std::strtoul(argv[2], nullptr, 10);
  if (parsed == 0 || parsed > UINT32_MAX) {
    std::fprintf(stderr, "invalid process id\n");
    return 2;
  }

  if (_setmode(_fileno(stdout), _O_BINARY) == -1) {
    std::fprintf(stderr, "failed to put stdout in binary mode\n");
    return 2;
  }
  std::setvbuf(stdout, nullptr, _IONBF, 0);

  const HRESULT initialized =
      CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  if (FAILED(initialized)) {
    printError("CoInitializeEx", initialized);
    return 2;
  }

  const ProcessLoopbackMode mode =
      std::strcmp(argv[1], "--include-pid") == 0
          ? ProcessLoopbackMode::kIncludeTargetProcessTree
          : ProcessLoopbackMode::kExcludeTargetProcessTree;
  timeBeginPeriod(1);
  const int result = capture(static_cast<DWORD>(parsed), mode);
  timeEndPeriod(1);
  CoUninitialize();
  return result;
}
