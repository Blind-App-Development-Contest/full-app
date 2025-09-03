class StepMeasurementResult {
  // === 통일된 변수명 (시각장애인 접근성 고려) ===
  final double step_length_cm;  // 보폭 (cm) - 백엔드와 동일한 변수명
  final int stepCount;          // 걸음 수 - 모든 곳에서 이 이름 사용  
  final double? distanceMeters; // 총 이동거리 (m) - 모든 곳에서 이 이름 사용
  
  // === 측정 품질 정보 ===
  final double confidence;
  final String trackingQuality;
  final String accuracyLevel;
  final String measurementMethod;
  final Map<String, dynamic>? sourceData;
  final double? processingTimeMs;
  
  // === 시각장애인을 위한 상수들 ===
  static const double defaultStepLengthCm = 75.0;
  static const double minValidStepLengthCm = 40.0;
  static const double maxValidStepLengthCm = 120.0;
  static const int defaultMeasurementSteps = 10;

  const StepMeasurementResult({
    required this.step_length_cm,
    required this.confidence,
    required this.stepCount,
    required this.trackingQuality,
    required this.accuracyLevel,
    required this.measurementMethod,
    this.sourceData,
    this.processingTimeMs,
    this.distanceMeters,
  });

  factory StepMeasurementResult.fromJson(Map<String, dynamic> json) {
    final stepLengthCm = (json['step_length_cm'] ?? 0.0).toDouble();
    final steps = json['step_count'] ?? 0;
    
    return StepMeasurementResult(
      step_length_cm: stepLengthCm,
      confidence: (json['confidence'] ?? 0.0).toDouble(),
      stepCount: steps,
      trackingQuality: json['tracking_quality'] ?? 'poor',
      accuracyLevel: json['accuracy_level'] ?? '낮음',
      measurementMethod: json['measurement_method'] ?? 'unknown',
      sourceData: json['source_data'],
      processingTimeMs: json['processing_time_ms']?.toDouble(),
      distanceMeters: json['distance_meters']?.toDouble() ?? 
                     (steps > 0 ? (stepLengthCm * steps) / 100.0 : null), // cm를 m로 변환
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'step_length_cm': step_length_cm,
      'confidence': confidence,
      'step_count': stepCount,
      'tracking_quality': trackingQuality,
      'accuracy_level': accuracyLevel,
      'measurement_method': measurementMethod,
      'source_data': sourceData,
      'processing_time_ms': processingTimeMs,
      'distance_meters': distanceMeters,
    };
  }

  bool get isHighAccuracy => confidence >= 0.8;
  bool get isLowAccuracy => confidence < 0.6;

  String get confidencePercentage =>
      '${(confidence * 100).toStringAsFixed(1)}%';

  // 계산된 총 이동거리 (미터)
  double get calculatedDistance {
    return distanceMeters ?? ((step_length_cm * stepCount) / 100.0);
  }

  // === 시각장애인을 위한 유틸리티 메서드들 ===
  
  /// 보폭 유효성 검증
  bool get isValidStepLength => 
      step_length_cm >= minValidStepLengthCm && step_length_cm <= maxValidStepLengthCm;
  
  /// 정확도 기반 음성 설명
  String get accuracyVoiceDescription {
    if (confidence >= 0.9) return "매우 정확한 측정입니다";
    if (confidence >= 0.8) return "정확한 측정입니다";
    if (confidence >= 0.6) return "보통 수준의 측정입니다. 더 정확한 측정을 위해 평지에서 직선으로 걸어보세요.";
    if (confidence >= 0.4) return "낮은 정확도의 측정입니다. 측정 환경을 점검하고 다시 시도해보세요.";
    return "매우 낮은 정확도의 측정입니다. 평평하고 장애물이 없는 곳에서 천천히 직선으로 걸어보세요.";
  }
  
  /// 시각장애인용 상세 음성 안내 텍스트
  String get detailedVoiceDescription {
    final distanceText = calculatedDistance > 0 
        ? ", 총 이동거리는 ${calculatedDistance.toStringAsFixed(1)}미터입니다" 
        : "";

    return "측정된 보폭은 ${step_length_cm.toStringAsFixed(1)}센티미터이며, "
        "총 $stepCount걸음을 기록했습니다$distanceText. $accuracyVoiceDescription.";
  }
  
  /// 통일된 변수명으로 기본값 생성
  static StepMeasurementResult createDefault({
    double? customStepLength,
    int? customStepCount,
  }) {
    final stepLen = customStepLength ?? defaultStepLengthCm;
    final stepCnt = customStepCount ?? defaultMeasurementSteps;
    
    return StepMeasurementResult(
      step_length_cm: stepLen,
      confidence: 0.7,
      stepCount: stepCnt,
      trackingQuality: 'good',
      accuracyLevel: '보통',
      measurementMethod: 'default',
      distanceMeters: (stepLen * stepCnt) / 100.0,
    );
  }
}
