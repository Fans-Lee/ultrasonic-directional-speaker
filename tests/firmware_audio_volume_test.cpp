#include <assert.h>
#include <initializer_list>

#include "audio_modulator.h"
#include "audio_volume.h"

using namespace ultrasonic;

int main() {
  AudioVolume volume;
  assert(volume.targetPermille() == 1000);
  assert(volume.currentGainQ15() == AudioVolume::kUnityGainQ15);

  volume.setTargetPermille(500, true);
  const uint32_t middle = volume.currentGainQ15();
  assert(middle > 0 && middle < AudioVolume::kUnityGainQ15);
  volume.setTargetPermille(10, true);
  const uint32_t quietest = volume.currentGainQ15();
  assert(quietest > 0 && quietest < middle);
  volume.setTargetPermille(500, true);
  volume.setTargetPermille(0, false);
  volume.advance(AudioVolume::kRampSamples / 2);
  assert(volume.currentGainQ15() > 0);
  assert(volume.currentGainQ15() < middle);
  volume.advance(AudioVolume::kRampSamples / 2);
  assert(volume.off());

  volume.setTargetPermille(1000, false);
  volume.advance(AudioVolume::kRampSamples + 500);
  assert(volume.currentGainQ15() == AudioVolume::kUnityGainQ15);

  AudioModulator modulator;
  assert(modulator.begin({1024, 512}));
  for (AudioModulationMode modulation : {AudioModulationMode::kDsbAm,
                                         AudioModulationMode::kSram}) {
    for (AudioProcessingMode processing : {AudioProcessingMode::kRaw,
                                           AudioProcessingMode::kLoudnessEnhanced}) {
      const uint32_t silence = modulator.dutyForSample(
          128, modulation, processing, AudioDriveMode::kBoost, 32768);
      const uint32_t full = modulator.dutyForSample(
          220, modulation, processing, AudioDriveMode::kBoost, 32768);
      const uint32_t quiet = modulator.dutyForSample(
          220, modulation, processing, AudioDriveMode::kBoost, middle);
      assert(full > quiet && quiet >= silence);
      const uint32_t low = modulator.dutyForSample(
          40, modulation, processing, AudioDriveMode::kBoost, middle);
      const uint32_t lowFull = modulator.dutyForSample(
          40, modulation, processing, AudioDriveMode::kBoost, 32768);
      assert(lowFull < low && low <= silence);
      assert(modulator.dutyForSample(
                 220, modulation, processing, AudioDriveMode::kBoost, 0) == 0);
    }
  }
  return 0;
}
