import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import uuid
import math

@dataclass
class Person:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    center: Tuple[int, int] = (0, 0)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    last_movement: datetime = field(default_factory=datetime.now)
    disappeared_frames: int = 0
    movement_history: List[Tuple[int, int]] = field(default_factory=list)
    is_idle: bool = False
    idle_start_time: Optional[datetime] = None
    confidence: float = 0.0

    def update_position(self, center: Tuple[int, int], bbox: Tuple[int, int, int, int], confidence: float, movement_threshold: int = 20):
        """Update person position and check for movement"""
        old_center = self.center
        self.center = center
        self.bbox = bbox
        self.confidence = confidence
        self.last_seen = datetime.now()
        self.disappeared_frames = 0
        
        # Calculate movement distance
        if old_center != (0, 0):
            distance = math.sqrt((center[0] - old_center[0])**2 + (center[1] - old_center[1])**2)
            if distance > movement_threshold:
                self.last_movement = datetime.now()
                self.idle_start_time = None
                self.is_idle = False
            elif self.idle_start_time is None:
                self.idle_start_time = datetime.now()
        
        # Keep movement history (last 10 positions)
        self.movement_history.append(center)
        if len(self.movement_history) > 10:
            self.movement_history.pop(0)

    def check_idle_status(self, idle_threshold_seconds: int = 30) -> bool:
        """Check if person has been idle for the threshold time"""
        if self.idle_start_time is None:
            return False
            
        idle_duration = datetime.now() - self.idle_start_time
        self.is_idle = idle_duration.total_seconds() >= idle_threshold_seconds
        return self.is_idle

    def mark_disappeared(self):
        """Mark person as disappeared for one frame"""
        self.disappeared_frames += 1

    def to_dict(self) -> Dict:
        """Convert person to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'center': self.center,
            'bbox': self.bbox,
            'first_seen': self.first_seen.isoformat(),
            'last_seen': self.last_seen.isoformat(),
            'last_movement': self.last_movement.isoformat(),
            'is_idle': self.is_idle,
            'idle_duration': (datetime.now() - self.idle_start_time).total_seconds() if self.idle_start_time else 0,
            'confidence': self.confidence,
            'movement_history': self.movement_history[-5:]  # Last 5 positions
        }


class PersonTracker:
    def __init__(self, max_disappeared: int = 30, max_distance: int = 100):
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
        self.persons: Dict[str, Person] = {}
        self.next_id = 0

    def update(self, detections: List[Tuple[Tuple[int, int, int, int], float]], movement_threshold: int = 20, idle_threshold: int = 30) -> List[Person]:
        """
        Update tracker with new detections
        detections: List of ((x, y, w, h), confidence) tuples
        """
        if len(detections) == 0:
            # Mark all existing persons as disappeared
            for person in self.persons.values():
                person.mark_disappeared()
            
            # Remove persons that have been gone too long
            self._cleanup_disappeared()
            return list(self.persons.values())

        # Convert detections to centers
        detection_centers = []
        for (x, y, w, h), confidence in detections:
            center_x = x + w // 2
            center_y = y + h // 2
            detection_centers.append(((center_x, center_y), (x, y, w, h), confidence))

        # If no existing persons, create new ones
        if len(self.persons) == 0:
            for (center, bbox, confidence) in detection_centers:
                person = Person()
                person.update_position(center, bbox, confidence, movement_threshold)
                self.persons[person.id] = person
        else:
            # Match existing persons with detections
            self._match_detections(detection_centers, movement_threshold)

        # Update idle status for all persons
        for person in self.persons.values():
            person.check_idle_status(idle_threshold)

        # Cleanup disappeared persons
        self._cleanup_disappeared()

        return list(self.persons.values())

    def _match_detections(self, detection_centers: List[Tuple[Tuple[int, int], Tuple[int, int, int, int], float]], movement_threshold: int):
        """Match detections with existing persons using minimum distance"""
        person_centers = [(pid, person.center) for pid, person in self.persons.items()]
        
        if len(person_centers) == 0:
            # Create new persons for all detections
            for (center, bbox, confidence) in detection_centers:
                person = Person()
                person.update_position(center, bbox, confidence, movement_threshold)
                self.persons[person.id] = person
            return

        # Calculate distance matrix
        matches = []
        for i, (center, bbox, confidence) in enumerate(detection_centers):
            min_distance = float('inf')
            best_match = None
            
            for pid, person_center in person_centers:
                distance = math.sqrt((center[0] - person_center[0])**2 + (center[1] - person_center[1])**2)
                if distance < min_distance and distance < self.max_distance:
                    min_distance = distance
                    best_match = pid
            
            if best_match is not None:
                matches.append((best_match, center, bbox, confidence))
                # Remove matched person from available matches
                person_centers = [(pid, pc) for pid, pc in person_centers if pid != best_match]

        # Update matched persons
        matched_person_ids = set()
        for pid, center, bbox, confidence in matches:
            if pid in self.persons:
                self.persons[pid].update_position(center, bbox, confidence, movement_threshold)
                matched_person_ids.add(pid)

        # Mark unmatched existing persons as disappeared
        for pid in self.persons:
            if pid not in matched_person_ids:
                self.persons[pid].mark_disappeared()

        # Create new persons for unmatched detections
        unmatched_detections = detection_centers[len(matches):]
        for (center, bbox, confidence) in unmatched_detections:
            person = Person()
            person.update_position(center, bbox, confidence, movement_threshold)
            self.persons[person.id] = person

    def _cleanup_disappeared(self):
        """Remove persons that have been disappeared for too long"""
        to_remove = []
        for pid, person in self.persons.items():
            if person.disappeared_frames > self.max_disappeared:
                to_remove.append(pid)
        
        for pid in to_remove:
            del self.persons[pid]

    def get_active_persons(self) -> List[Person]:
        """Get all currently active (not disappeared) persons"""
        return [person for person in self.persons.values() if person.disappeared_frames == 0]

    def get_idle_persons(self) -> List[Person]:
        """Get all currently idle persons"""
        return [person for person in self.persons.values() if person.is_idle and person.disappeared_frames == 0]

    def reset(self):
        """Reset tracker - remove all persons"""
        self.persons.clear()
        self.next_id = 0