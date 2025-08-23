from datetime import datetime, timedelta
from typing import List, Tuple, Generator
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass
class DateRange:
    """Represents a date range for scraping"""
    start_date: datetime
    end_date: datetime
    
    def to_string_format(self) -> Tuple[str, str]:
        """Convert to string format expected by the website (dd-mm-yyyy)"""
        start_str = self.start_date.strftime("%d-%m-%Y")
        end_str = self.end_date.strftime("%d-%m-%Y")
        return start_str, end_str
    
    def __str__(self) -> str:
        start_str, end_str = self.to_string_format()
        return f"{start_str} to {end_str}"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DateRange':
        """Create from dictionary"""
        return cls(
            start_date=datetime.fromisoformat(data["start_date"]),
            end_date=datetime.fromisoformat(data["end_date"])
        )

class DateManager:
    """Manages date ranges for scraping Supreme Court judgments"""
    
    def __init__(self, start_year: int, end_year: int, max_days: int = 30):
        self.start_year = start_year
        self.end_year = end_year
        self.max_days = max_days
        self.progress_file = "date_progress.json"
        
    def generate_date_ranges(self) -> Generator[DateRange, None, None]:
        """Generate date ranges in chunks of max_days"""
        start_date = datetime(self.start_year, 1, 1)
        end_date = datetime(self.end_year, 12, 31)
        
        current_date = start_date
        
        while current_date <= end_date:
            # Calculate the end of current chunk
            chunk_end = min(
                current_date + timedelta(days=self.max_days - 1),
                end_date
            )
            
            yield DateRange(current_date, chunk_end)
            
            # Move to next chunk
            current_date = chunk_end + timedelta(days=1)
    
    def get_all_date_ranges(self) -> List[DateRange]:
        """Get all date ranges as a list"""
        return list(self.generate_date_ranges())
    
    def get_total_ranges_count(self) -> int:
        """Get total number of date ranges"""
        return len(self.get_all_date_ranges())
    
    def save_progress(self, completed_ranges: List[DateRange], failed_ranges: List[DateRange] = None):
        """Save progress to file"""
        if failed_ranges is None:
            failed_ranges = []
            
        progress_data = {
            "completed_ranges": [r.to_dict() for r in completed_ranges],
            "failed_ranges": [r.to_dict() for r in failed_ranges],
            "last_updated": datetime.now().isoformat(),
            "total_completed": len(completed_ranges),
            "total_failed": len(failed_ranges)
        }
        
        with open(self.progress_file, 'w') as f:
            json.dump(progress_data, f, indent=2)
    
    def load_progress(self) -> Tuple[List[DateRange], List[DateRange]]:
        """Load progress from file"""
        if not Path(self.progress_file).exists():
            return [], []
        
        try:
            with open(self.progress_file, 'r') as f:
                progress_data = json.load(f)
            
            completed_ranges = [
                DateRange.from_dict(r) for r in progress_data.get("completed_ranges", [])
            ]
            failed_ranges = [
                DateRange.from_dict(r) for r in progress_data.get("failed_ranges", [])
            ]
            
            return completed_ranges, failed_ranges
        except Exception as e:
            print(f"Error loading progress: {e}")
            return [], []
    
    def get_remaining_ranges(self) -> List[DateRange]:
        """Get remaining date ranges to process"""
        all_ranges = self.get_all_date_ranges()
        completed_ranges, failed_ranges = self.load_progress()
        
        # Convert to sets for faster lookup
        completed_set = {(r.start_date, r.end_date) for r in completed_ranges}
        
        # Return ranges that haven't been completed
        remaining = [
            r for r in all_ranges 
            if (r.start_date, r.end_date) not in completed_set
        ]
        
        # Add failed ranges to retry
        remaining.extend(failed_ranges)
        
        return remaining
    
    def get_progress_summary(self) -> dict:
        """Get progress summary"""
        total_ranges = self.get_total_ranges_count()
        completed_ranges, failed_ranges = self.load_progress()
        remaining_ranges = self.get_remaining_ranges()
        
        return {
            "total_ranges": total_ranges,
            "completed": len(completed_ranges),
            "failed": len(failed_ranges),
            "remaining": len(remaining_ranges),
            "completion_percentage": (len(completed_ranges) / total_ranges) * 100 if total_ranges > 0 else 0,
            "date_span": f"{self.start_year} to {self.end_year}",
            "max_days_per_range": self.max_days
        }
    
    def reset_progress(self):
        """Reset progress file"""
        if Path(self.progress_file).exists():
            Path(self.progress_file).unlink()

# Example usage and testing
if __name__ == "__main__":
    # Test the date manager
    dm = DateManager(2020, 2021, 30)  # Test with 2 years
    
    print("Date Manager Test:")
    print(f"Total ranges: {dm.get_total_ranges_count()}")
    
    # Show first few ranges
    ranges = dm.get_all_date_ranges()
    print("\nFirst 5 date ranges:")
    for i, date_range in enumerate(ranges[:5]):
        print(f"{i+1}. {date_range}")
    
    # Test progress tracking
    print("\nProgress Summary:")
    summary = dm.get_progress_summary()
    for key, value in summary.items():
        print(f"{key}: {value}")