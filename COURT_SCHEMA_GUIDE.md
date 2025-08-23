# Court Hierarchy Schema Guide

This document explains the updated judgment schema that supports multiple court types in the Indian judicial system.

## Court Hierarchy Structure

The schema now supports four levels of courts:

### 1. Supreme Court (Level 1)
- **court_type**: `"supreme_court"`
- **court_level**: `1`
- **court_name**: `"Supreme Court of India"`
- **jurisdiction**: `"India"`

### 2. High Courts (Level 2)
- **court_type**: `"high_court"`
- **court_level**: `2`
- **court_name**: Examples: `"Delhi High Court"`, `"Bombay High Court"`, `"Madras High Court"`
- **jurisdiction**: State/UT name (e.g., `"Delhi"`, `"Maharashtra"`, `"Tamil Nadu"`)

### 3. District Courts (Level 3)
- **court_type**: `"district_court"`
- **court_level**: `3`
- **court_name**: Examples: `"District Court Delhi"`, `"District Court Mumbai"`
- **jurisdiction**: District name

### 4. Tribunals (Level 4)
- **court_type**: `"tribunal"`
- **court_level**: `4`
- **court_name**: Examples: `"National Green Tribunal"`, `"Income Tax Appellate Tribunal"`
- **jurisdiction**: Varies by tribunal type

## Schema Fields

### New Court Hierarchy Fields
```python
court_type: str = "supreme_court"  # supreme_court, high_court, district_court, tribunal
court_level: int = 1  # 1=Supreme, 2=High, 3=District, 4=Tribunal
court_name: Optional[str] = None  # Specific court name
jurisdiction: Optional[str] = None  # State/Region jurisdiction
```

### Existing Fields (Unchanged)
- All existing judgment metadata fields remain the same
- Backward compatibility is maintained
- Legacy field mappings are preserved

## Database Indexes

New indexes have been added for efficient querying:
- `court_type` (single field index)
- `court_level` (single field index)
- `court_type + court_level` (compound index)
- `court_type + case_number + judgment_date` (compound index)
- Text search now includes `court_name`

## Usage Examples

### Querying by Court Type
```python
# Get all Supreme Court judgments
supreme_judgments = mongo_client.get_judgments_by_court_type("supreme_court")

# Get all High Court judgments
high_court_judgments = mongo_client.get_judgments_by_court_type("high_court")
```

### Querying by Court Level
```python
# Get all Level 1 (Supreme Court) judgments
level_1_judgments = mongo_client.get_judgments_by_court_level(1)

# Get all Level 2 (High Court) judgments
level_2_judgments = mongo_client.get_judgments_by_court_level(2)
```

### Querying by Court Type and Status
```python
# Get pending Supreme Court judgments
pending_supreme = mongo_client.get_judgments_by_court_and_status("supreme_court", "pending")
```

### Statistics with Court Breakdown
```python
stats = mongo_client.get_statistics()
print(f"Court type breakdown: {stats['court_type_breakdown']}")
print(f"Court level breakdown: {stats['court_level_breakdown']}")
```

## Migration Notes

- Existing Supreme Court judgments will have default values:
  - `court_type`: `"supreme_court"`
  - `court_level`: `1`
  - `court_name`: `"Supreme Court of India"`
  - `jurisdiction`: `"India"`

- The current scraper automatically sets these values for new Supreme Court judgments

- Future scrapers for High Courts, District Courts, and Tribunals should set appropriate values for their respective court types

## Future Scraper Implementation

When implementing scrapers for other court types, ensure to set the correct court hierarchy fields:

```python
# Example for High Court scraper
metadata = JudgmentMetadata(
    judgment_id=judgment_id,
    court_type="high_court",
    court_level=2,
    court_name="Delhi High Court",
    jurisdiction="Delhi",
    # ... other fields
)

# Example for District Court scraper
metadata = JudgmentMetadata(
    judgment_id=judgment_id,
    court_type="district_court",
    court_level=3,
    court_name="District Court Delhi",
    jurisdiction="Delhi",
    # ... other fields
)

# Example for Tribunal scraper
metadata = JudgmentMetadata(
    judgment_id=judgment_id,
    court_type="tribunal",
    court_level=4,
    court_name="National Green Tribunal",
    jurisdiction="India",
    # ... other fields
)
```

This schema design provides a scalable foundation for collecting judgments from all levels of the Indian judicial system while maintaining backward compatibility with existing Supreme Court data.