# Implementation Plan: ESP32 Real-Time AI Assistant with TTS

## Overview

This implementation plan extends the existing "esp32-asr-capture-vision-mvp" system by adding three new components (Question_Trigger_Engine, TTS_Adapter, Audio_Playback_Coordinator) and extending the ESP32 firmware with I2S audio output capabilities. The implementation follows an incremental approach, building and testing each component before integration.

## Tasks

- [x] 1. Set up TTS service integration and configuration
  - Create TTS service client wrapper for Qwen TTS or compatible service
  - Implement configuration management for TTS parameters (voice, speed, pitch, format)
  - Add TTS service credentials and endpoint configuration
  - Write unit tests for TTS client wrapper
  - _Requirements: 5.1, 5.2, 5.3, 12.1, 12.2_

- [x] 2. Implement Question_Trigger_Engine component
  - [x] 2.1 Create Question_Trigger_Engine class with Event_Bus integration
    - Implement trigger phrase detection logic with fuzzy matching
    - Add cooldown mechanism to prevent overlapping requests
    - Implement question text extraction from transcriptions
    - Subscribe to ASR transcription events
    - Emit capture trigger events with question context
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 12.3_
  
  - [x] 2.2 Write property test for trigger detection and question extraction
    - **Property 3: Trigger detection and question extraction**
    - **Validates: Requirements 2.1, 2.5**
  
  - [x] 2.3 Write property test for cooldown prevention
    - **Property 4: Cooldown prevention**
    - **Validates: Requirements 2.4**
  
  - [x] 2.4 Write unit tests for specific trigger phrases
    - Test each English trigger phrase individually
    - Test each Chinese trigger phrase individually
    - Test fuzzy matching with variations
    - _Requirements: 2.2, 2.3_

- [x] 3. Implement TTS_Adapter component
  - [x] 3.1 Create TTS_Adapter class with Event_Bus integration
    - Subscribe to vision response events
    - Implement text-to-speech conversion using TTS service
    - Add retry logic for TTS failures
    - Emit audio-ready events with audio data
    - Handle error scenarios with fallback messages
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  
  - [x] 3.2 Write property test for TTS conversion pipeline
    - **Property 10: TTS conversion pipeline**
    - **Validates: Requirements 5.1, 5.3, 5.5**
  
  - [x] 3.3 Write property test for TTS retry logic
    - **Property 11: TTS retry logic**
    - **Validates: Requirements 5.4**
  
  - [x] 3.4 Write unit tests for TTS error handling
    - Test TTS service failure scenarios
    - Test fallback to pre-recorded error messages
    - Test Chinese language support
    - _Requirements: 5.2, 5.4, 8.5_

- [x] 4. Implement Audio_Playback_Coordinator component
  - [x] 4.1 Create Audio_Playback_Coordinator class with WebSocket integration
    - Subscribe to audio-ready events
    - Implement audio streaming to ESP32 via WebSocket
    - Add playback state management (prevent concurrent playback)
    - Handle playback completion events from ESP32
    - Implement streaming resilience (resume/restart on interruption)
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 12.2_
  
  - [x] 4.2 Write property test for audio streaming to ESP32
    - **Property 12: Audio streaming to ESP32**
    - **Validates: Requirements 6.1, 6.5**
  
  - [x] 4.3 Write property test for playback mutual exclusion
    - **Property 13: Playback mutual exclusion**
    - **Validates: Requirements 6.3**
  
  - [x] 4.4 Write property test for audio streaming resilience
    - **Property 14: Audio streaming resilience**
    - **Validates: Requirements 6.4**
  
  - [x] 4.5 Write unit tests for playback state management
    - Test concurrent request rejection
    - Test playback completion handling
    - Test WebSocket disconnection scenarios
    - _Requirements: 6.3, 6.4_

- [x] 5. Extend ESP32 firmware with I2S audio output
  - [x] 5.1 Implement I2S audio output configuration
    - Configure I2S peripheral for audio output (16kHz, 16-bit, mono)
    - Set up I2S pins (BCK, WS, DATA_OUT)
    - Initialize I2S driver with DMA buffers
    - _Requirements: 6.2_
  
  - [x] 5.2 Implement audio buffer management
    - Create ring buffer for audio data (16KB)
    - Implement buffer write/read operations
    - Add buffer level monitoring (request more data when low)
    - Implement buffer pre-fill before playback
    - _Requirements: 9.2, 9.3, 11.2_
  
  - [x] 5.3 Implement audio playback control
    - Add WebSocket message handler for audio chunks
    - Implement audio playback via I2S
    - Add playback state management (playing/stopped)
    - Send playback completion message to backend
    - _Requirements: 6.2, 6.5_
  
  - [x] 5.4 Write property test for buffer request on low buffer
    - **Property 16: Buffer request on low buffer**
    - **Validates: Requirements 9.2**
  
  - [x] 5.5 Write property test for buffer pre-fill before playback
    - **Property 17: Buffer pre-fill before playback**
    - **Validates: Requirements 9.3**
  
  - [x] 5.6 Write property test for memory cleanup after playback
    - **Property 18: Memory cleanup after playback**
    - **Validates: Requirements 11.2**

- [x] 6. Checkpoint - Test individual components
  - Ensure all component unit tests pass
  - Verify Question_Trigger_Engine detects trigger phrases correctly
  - Verify TTS_Adapter converts text to audio successfully
  - Verify Audio_Playback_Coordinator streams audio correctly
  - Verify ESP32 firmware plays audio through I2S
  - Ask the user if questions arise

- [x] 7. Implement error handling and recovery
  - [x] 7.1 Create error message generation system
    - Implement error message mapping for each error type
    - Add pre-recorded error message support
    - Integrate error messages with TTS_Adapter
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  
  - [x] 7.2 Implement retry logic for capture and vision
    - Add retry logic to capture coordinator (up to 2 retries)
    - Add timeout enforcement for vision processing (8 seconds)
    - Add fallback responses for vision errors
    - _Requirements: 3.3, 4.4, 4.5_
  
  - [x] 7.3 Write property test for error message generation
    - **Property 15: Error message generation**
    - **Validates: Requirements 8.1**
  
  - [x] 7.4 Write property test for capture retry logic
    - **Property 6: Capture retry logic**
    - **Validates: Requirements 3.3**
  
  - [x] 7.5 Write property test for vision timeout enforcement
    - **Property 8: Vision timeout enforcement**
    - **Validates: Requirements 4.4**
  
  - [x] 7.6 Write property test for vision error handling
    - **Property 9: Vision error handling**
    - **Validates: Requirements 4.5**
  
  - [x] 7.7 Write unit tests for specific error messages
    - Test ASR failure error message
    - Test camera failure error message
    - Test vision failure error message
    - Test TTS failure error message
    - Test network loss error message
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 8. Implement resource management and concurrency control
  - [x] 8.1 Add concurrent request limitation
    - Implement request queue with single active request
    - Reject new requests when one is in progress
    - Release lock on playback completion or error
    - _Requirements: 11.3_
  
  - [x] 8.2 Add low memory protection for ESP32
    - Monitor ESP32 memory usage
    - Reject requests when memory is low
    - Play memory error message
    - _Requirements: 11.4_
  
  - [x] 8.3 Write property test for concurrent request limitation
    - **Property 19: Concurrent request limitation**
    - **Validates: Requirements 11.3**
  
  - [x] 8.4 Write property test for low memory protection
    - **Property 20: Low memory protection**
    - **Validates: Requirements 11.4**

- [x] 9. Integrate components with existing system
  - [x] 9.1 Wire Question_Trigger_Engine to Event_Bus
    - Subscribe to ASR transcription events
    - Verify trigger detection triggers image capture
    - Test end-to-end flow: transcription → trigger → capture
    - _Requirements: 10.3_
  
  - [x] 9.2 Wire TTS_Adapter to Event_Bus
    - Subscribe to vision response events
    - Verify TTS conversion produces audio
    - Test end-to-end flow: vision response → TTS → audio ready
    - _Requirements: 10.1_
  
  - [x] 9.3 Wire Audio_Playback_Coordinator to WebSocket_Gateway
    - Subscribe to audio-ready events
    - Verify audio streaming to ESP32
    - Test end-to-end flow: audio ready → stream → playback
    - _Requirements: 10.2_
  
  - [x] 9.4 Modify Vision_Adapter to accept question context
    - Update Vision_Adapter to receive question text
    - Pass question to Qwen-Omni-Flash as prompt context
    - Verify vision responses include question context
    - _Requirements: 4.1_
  
  - [x] 9.5 Write property test for image-question association
    - **Property 5: Image-question association**
    - **Validates: Requirements 3.4**
  
  - [x] 9.6 Write property test for vision request completeness
    - **Property 7: Vision request completeness**
    - **Validates: Requirements 4.1, 4.3**

- [x] 10. Checkpoint - Test integrated system
  - Ensure all integration tests pass
  - Verify end-to-end flow: question → capture → vision → TTS → playback
  - Test error scenarios and recovery
  - Test concurrent request handling
  - Ask the user if questions arise

- [x] 11. Implement network resilience
  - [x] 11.1 Add audio buffering for network interruptions
    - Implement local audio buffering on ESP32
    - Resume streaming after network restoration
    - _Requirements: 1.3_
  
  - [x] 11.2 Add WebSocket reconnection logic
    - Implement automatic reconnection with exponential backoff
    - Play network error message on disconnection
    - Resume operation after reconnection
    - _Requirements: 8.6_
  
  - [x] 11.3 Write property test for network resilience with buffering
    - **Property 2: Network resilience with buffering**
    - **Validates: Requirements 1.3**

- [x] 12. Add configuration and customization support
  - [x] 12.1 Create configuration file structure
    - Define configuration schema for all components
    - Add configuration loading and validation
    - Support environment variable overrides
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_
  
  - [x] 12.2 Implement pluggable TTS backend support
    - Create TTS backend interface
    - Implement Qwen TTS backend
    - Support custom TTS backend registration
    - _Requirements: 12.5_
  
  - [x] 12.3 Write unit tests for configuration loading
    - Test TTS voice parameter configuration
    - Test audio format configuration
    - Test trigger phrase configuration from file
    - Test timeout configuration
    - Test pluggable TTS backend
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [x] 13. End-to-end integration testing
  - [x] 13.1 Write integration test for happy path
    - Test: User asks question → receives spoken response
    - Verify all components work together
    - Verify response time is within acceptable range
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 5.1, 6.1_
  
  - [x] 13.2 Write integration test for network interruption recovery
    - Test: Connection lost during audio streaming → recovery
    - Verify buffering and resume behavior
    - _Requirements: 1.3, 6.4, 8.6_
  
  - [x] 13.3 Write integration test for concurrent request handling
    - Test: Multiple questions in quick succession → cooldown enforcement
    - Verify only first request is processed
    - _Requirements: 2.4, 11.3_
  
  - [x] 13.4 Write integration test for error recovery
    - Test: Component failure → error message → system recovery
    - Verify error messages are spoken
    - Verify system recovers and accepts new requests
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  
  - [x] 13.5 Write integration test for low memory scenario
    - Test: ESP32 low memory → request rejection → memory cleanup
    - Verify memory error message is played
    - Verify system recovers after memory cleanup
    - _Requirements: 11.2, 11.4_

- [x] 14. Final checkpoint and documentation
  - Ensure all tests pass (unit, property, integration)
  - Verify system meets performance targets (<10 seconds end-to-end)
  - Update API documentation with new endpoints and events
  - Update deployment guide with TTS service configuration
  - Ask the user if questions arise

## Notes

- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties across randomized inputs
- Unit tests validate specific examples, edge cases, and error conditions
- Integration tests validate end-to-end system behavior
- The implementation reuses existing components (ASR_Bridge, Vision_Adapter, Event_Bus, WebSocket_Gateway) without modification where possible
