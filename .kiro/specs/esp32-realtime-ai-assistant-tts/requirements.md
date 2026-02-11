# Requirements Document: ESP32 Real-Time AI Assistant with TTS

## Introduction

This document specifies the requirements for a real-time AI assistant feature designed for visually impaired users using ESP32 smart glasses. The system enables users to ask questions about their surroundings through voice commands and receive spoken responses through an ESP32 speaker. The feature extends the existing "esp32-asr-capture-vision-mvp" system by adding text-to-speech capabilities and audio playback functionality.

## Glossary

- **ESP32**: Microcontroller device with camera, microphone, and speaker capabilities
- **ASR_Bridge**: Automatic Speech Recognition service that converts audio to text using Qwen3-ASR-Flash-Realtime
- **Vision_Adapter**: Service that processes images using Qwen-Omni-Flash vision model
- **TTS_Adapter**: Text-to-Speech service that converts text responses to audio
- **Audio_Playback_Coordinator**: Component managing audio streaming and playback on ESP32
- **Question_Trigger_Engine**: Component detecting question phrases in transcribed text
- **WebSocket_Gateway**: Bidirectional communication channel between ESP32 and backend
- **Event_Bus**: Message broker for inter-component communication
- **I2S**: Inter-IC Sound protocol for digital audio transmission
- **PCM16**: Pulse Code Modulation 16-bit audio format
- **Trigger_Phrase**: Predefined question patterns that activate image capture

## Requirements

### Requirement 1: Audio Input Streaming

**User Story:** As a visually impaired user, I want to speak questions naturally, so that the system can understand what I'm asking about my surroundings.

#### Acceptance Criteria

1. WHEN the ESP32 microphone captures audio, THE System SHALL stream audio data to the backend via WebSocket in PCM16 format at 16kHz mono
2. WHEN audio streaming is active, THE ASR_Bridge SHALL process audio in real-time and produce text transcriptions
3. WHEN network interruption occurs, THE System SHALL buffer audio locally and resume streaming when connection is restored
4. WHEN audio quality is poor, THE System SHALL continue processing and indicate low confidence in transcription

### Requirement 2: Question Trigger Detection

**User Story:** As a visually impaired user, I want the system to automatically capture images when I ask questions, so that I don't need to press buttons.

#### Acceptance Criteria

1. WHEN the ASR_Bridge produces a transcription containing a trigger phrase, THE Question_Trigger_Engine SHALL detect the trigger and emit a capture event
2. THE Question_Trigger_Engine SHALL recognize English trigger phrases: "describe the view", "what do I see", "what's in front of me", "tell me what you see"
3. THE Question_Trigger_Engine SHALL recognize Chinese trigger phrases: "描述一下景象", "我看到什麼", "前面是什麼", "告訴我你看到什麼"
4. WHEN multiple trigger phrases are detected within 3 seconds, THE Question_Trigger_Engine SHALL process only the first trigger and ignore subsequent triggers until the current request completes
5. WHEN a trigger phrase is detected, THE Question_Trigger_Engine SHALL extract the user's question text for context

### Requirement 3: Automatic Image Capture

**User Story:** As a visually impaired user, I want the system to capture what's in front of me when I ask a question, so that the AI can describe my surroundings.

#### Acceptance Criteria

1. WHEN a question trigger is detected, THE System SHALL command the ESP32 to capture an image immediately
2. WHEN the ESP32 receives a capture command, THE ESP32 SHALL capture an image and stream it to the backend via WebSocket
3. WHEN image capture fails, THE System SHALL retry up to 2 times before reporting an error
4. WHEN an image is successfully captured, THE System SHALL associate the image with the user's question text

### Requirement 4: Vision Model Integration

**User Story:** As a visually impaired user, I want the AI to analyze images and answer my questions, so that I can understand my surroundings.

#### Acceptance Criteria

1. WHEN an image and question are available, THE Vision_Adapter SHALL send both to the Qwen-Omni-Flash vision model
2. WHEN the vision model processes the request, THE Vision_Adapter SHALL receive a text description as response
3. WHEN the vision model response is received, THE System SHALL format the response for natural speech output
4. WHEN vision processing takes longer than 8 seconds, THE System SHALL timeout and return an error message
5. WHEN the vision model returns an error, THE System SHALL generate a fallback response indicating the system cannot process the image

### Requirement 5: Text-to-Speech Conversion

**User Story:** As a visually impaired user, I want to hear spoken responses, so that I can understand the AI's description without reading.

#### Acceptance Criteria

1. WHEN the vision model returns a text description, THE TTS_Adapter SHALL convert the text to audio using a TTS service
2. THE TTS_Adapter SHALL support Chinese language output
3. THE TTS_Adapter SHALL generate audio in PCM16 format at 16kHz or MP3 format compatible with ESP32 playback
4. WHEN TTS conversion fails, THE System SHALL retry once before reporting an error
5. WHEN TTS processing completes, THE TTS_Adapter SHALL emit an audio-ready event with the audio data

### Requirement 6: Audio Playback Streaming

**User Story:** As a visually impaired user, I want to hear responses through my smart glasses speaker, so that I can receive information hands-free.

#### Acceptance Criteria

1. WHEN audio data is ready, THE Audio_Playback_Coordinator SHALL stream audio to the ESP32 via WebSocket
2. WHEN the ESP32 receives audio data, THE ESP32 SHALL play audio through the I2S speaker or DAC
3. WHEN audio playback is in progress, THE System SHALL prevent new question processing until playback completes
4. WHEN audio streaming is interrupted, THE System SHALL resume from the interruption point or restart playback
5. WHEN audio playback completes, THE System SHALL emit a playback-complete event to allow new questions

### Requirement 7: End-to-End Performance

**User Story:** As a visually impaired user, I want quick responses to my questions, so that the interaction feels natural and responsive.

#### Acceptance Criteria

1. WHEN a user asks a question, THE System SHALL complete the full cycle (ASR → trigger → capture → vision → TTS → playback) within 10 seconds
2. WHEN vision processing completes, THE System SHALL begin TTS conversion within 500 milliseconds
3. WHEN TTS audio is ready, THE System SHALL begin streaming to ESP32 within 200 milliseconds
4. THE System SHALL target a total response time of less than 5 seconds for optimal user experience

### Requirement 8: Error Handling and User Feedback

**User Story:** As a visually impaired user, I want to know when something goes wrong, so that I understand why I'm not getting a response.

#### Acceptance Criteria

1. WHEN any component fails, THE System SHALL generate a spoken error message appropriate to the failure type
2. WHEN ASR fails to transcribe audio, THE System SHALL play a message: "I couldn't understand that, please try again"
3. WHEN image capture fails, THE System SHALL play a message: "Camera unavailable, please try again"
4. WHEN vision processing fails, THE System SHALL play a message: "I couldn't analyze the image, please try again"
5. WHEN TTS fails, THE System SHALL log the error and attempt to send a pre-recorded error message
6. WHEN network connection is lost, THE System SHALL play a message: "Connection lost, reconnecting"

### Requirement 9: Audio Quality and Buffering

**User Story:** As a visually impaired user, I want clear audio without glitches, so that I can understand the responses easily.

#### Acceptance Criteria

1. WHEN streaming audio to ESP32, THE Audio_Playback_Coordinator SHALL implement buffering to prevent audio glitches
2. WHEN the ESP32 audio buffer is low, THE ESP32 SHALL request more audio data from the backend
3. WHEN audio playback begins, THE ESP32 SHALL ensure sufficient buffer before starting to prevent stuttering
4. THE System SHALL maintain audio synchronization to prevent speed variations or distortion

### Requirement 10: System Integration

**User Story:** As a system architect, I want the TTS feature to integrate with existing components, so that the system remains maintainable and extensible.

#### Acceptance Criteria

1. THE TTS_Adapter SHALL communicate with other components via the Event_Bus
2. THE Audio_Playback_Coordinator SHALL use the existing WebSocket_Gateway for audio streaming
3. THE Question_Trigger_Engine SHALL subscribe to ASR transcription events from the Event_Bus
4. WHEN the system initializes, THE System SHALL verify all required components are available before accepting user requests
5. THE System SHALL reuse the existing ASR_Bridge, Vision_Adapter, and Event_Bus components without modification

### Requirement 11: Resource Management

**User Story:** As a device user, I want the system to manage ESP32 resources efficiently, so that battery life is maximized.

#### Acceptance Criteria

1. WHEN no audio is being processed, THE ESP32 SHALL enter low-power mode for the speaker subsystem
2. WHEN audio playback completes, THE ESP32 SHALL release audio buffers to free memory
3. THE System SHALL limit concurrent audio processing to one request at a time to prevent memory exhaustion
4. WHEN the ESP32 memory is low, THE System SHALL reject new requests and play a memory error message

### Requirement 12: Configuration and Customization

**User Story:** As a system administrator, I want to configure TTS and audio parameters, so that the system can be optimized for different use cases.

#### Acceptance Criteria

1. THE TTS_Adapter SHALL support configurable voice parameters including speed, pitch, and volume
2. THE System SHALL support configurable audio format (PCM16 or MP3) based on ESP32 capabilities
3. THE Question_Trigger_Engine SHALL support configurable trigger phrases via configuration file
4. THE System SHALL support configurable timeout values for vision processing and TTS conversion
5. WHERE custom TTS services are configured, THE TTS_Adapter SHALL support pluggable TTS backends
