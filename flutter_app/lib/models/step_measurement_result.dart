class StepMeasurementResult {
  final double stepLength;
  final double confidence;
  final int stepCount;
  final String trackingQuality;
  final String accuracyLevel;
  final String measurementMethod;
  final Map<String, dynamic>? sourceData;
  final double? processingTimeMs;

  const StepMeasurementResult({
    required this.stepLength,
    required this.confidence,
    required this.stepCount,
    required this.trackingQuality,
    required this.accuracyLevel,
    required this.measurementMethod,
    this.sourceData,
    this.processingTimeMs,
  });

  factory StepMeasurementResult.fromJson(Map<String, dynamic> json) {
    return StepMeasurementResult(
      stepLength: (json['step_length_cm'] ?? 0.0).toDouble(),
      confidence: (json['confidence'] ?? 0.0).toDouble(),
      stepCount: json['step_count'] ?? 0,
      trackingQuality: json['tracking_quality'] ?? 'poor',
      accuracyLevel: json['accuracy_level'] ?? '낮음',
      measurementMethod: json['measurement_method'] ?? 'unknown',
      sourceData: json['source_data'],
      processingTimeMs: json['processing_time_ms']?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'step_length_cm': stepLength,
      'confidence': confidence,
      'step_count': stepCount,
      'tracking_quality': trackingQuality,
      'accuracy_level': accuracyLevel,
      'measurement_method': measurementMethod,
      'source_data': sourceData,
      'processing_time_ms': processingTimeMs,
    };
  }

  bool get isHighAccuracy => confidence >= 0.8;
  bool get isLowAccuracy => confidence < 0.6;

  String get confidencePercentage =>
      '${(confidence * 100).toStringAsFixed(1)}%';

  // 시각장애인용 상세 음성 안내 텍스트
  String get detailedVoiceDescription {
    String accuracyDescription;
    String recommendation = "";

    if (confidence >= 0.9) {
      accuracyDescription = "매우 정확한 측정입니다";
    } else if (confidence >= 0.8) {
      accuracyDescription = "정확한 측정입니다";
    } else if (confidence >= 0.6) {
      accuracyDescription = "보통 수준의 측정입니다";
      recommendation = " 더 정확한 측정을 위해 평지에서 직선으로 걸어보세요.";
    } else if (confidence >= 0.4) {
      accuracyDescription = "낮은 정확도의 측정입니다";
      recommendation = " 측정 환경을 점검하고 다시 시도해보세요.";
    } else {
      accuracyDescription = "매우 낮은 정확도의 측정입니다";
      recommendation = " 평평하고 장애물이 없는 곳에서 천천히 직선으로 걸어보세요.";
    }

    return "측정된 보폭은 ${stepLength.toStringAsFixed(1)}센티미터이며, "
        "총 ${stepCount}걸음을 기록했습니다. $accuracyDescription.$recommendation";
  }
}
