from django import template

register = template.Library()

@register.filter(name='split_commas')
def split_commas(value: str):
    """콤마(,)로 구분된 문자열을 트림하여 리스트로 반환. 빈 항목 제거."""
    if not value:
        return []
    # 한글 쉼표 변형 등 포함하여 표준 콤마 기준 split 후 트림
    parts = [p.strip() for p in value.replace('\n', ',').replace('，', ',').split(',')]
    return [p for p in parts if p]

