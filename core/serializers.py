from rest_framework import serializers
from .models import Facility, FacilityBasic, FacilityEvaluation, FacilityStaff, FacilityProgram, FacilityLocation, FacilityNonCovered

class FacilityBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityBasic
        fields = ['title', 'content']

class FacilityEvaluationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityEvaluation
        fields = ['title', 'content']

class FacilityStaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityStaff
        fields = ['title', 'content']

class FacilityProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityProgram
        fields = ['title', 'content']

class FacilityLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityLocation
        fields = ['title', 'content']

class FacilityNonCoveredSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityNonCovered
        fields = ['title', 'content']

class FacilityDetailSerializer(serializers.ModelSerializer):
    basic_items = FacilityBasicSerializer(many=True, read_only=True)
    evaluation_items = FacilityEvaluationSerializer(many=True, read_only=True)
    staff_items = FacilityStaffSerializer(many=True, read_only=True)
    program_items = FacilityProgramSerializer(many=True, read_only=True)
    location_items = FacilityLocationSerializer(many=True, read_only=True)
    noncovered_items = FacilityNonCoveredSerializer(many=True, read_only=True)

    class Meta:
        model = Facility
        fields = [
            'id', 'code', 'name', 'kind', 'grade', 'availability',
            'capacity', 'occupancy', 'waiting', 'created_at', 'updated_at',
            'basic_items', 'evaluation_items', 'staff_items', 'program_items',
            'location_items', 'noncovered_items'
        ]

class FacilityListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = [
            'id', 'code', 'name', 'kind', 'grade', 'availability',
            'capacity', 'occupancy', 'waiting'
        ]

class ChatRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=1000, help_text="사용자 질문")

class ChatResponseSerializer(serializers.Serializer):
    answer = serializers.CharField(help_text="생성된 답변")
    sources = serializers.ListField(help_text="참조된 요양원 정보")
    query = serializers.CharField(help_text="원본 질문")
