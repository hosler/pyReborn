"""
Cache Manager - Handles file caching with server-based organization
"""

import os
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class CacheManager:
    """Manages file caching with configurable paths and server organization"""
    
    def __init__(self, base_cache_dir: Optional[str] = None, disabled: bool = False):
        """Initialize cache manager
        
        Args:
            base_cache_dir: Base directory for cache. If None, uses default.
            disabled: If True, cache reads are disabled (always download fresh files)
        """
        self.disabled = disabled
        
        if self.disabled:
            logger.info("Cache READS are DISABLED - will always download fresh files")
        
        # Default cache location
        if base_cache_dir is None:
            # Use current working directory for cache
            base_cache_dir = os.path.join(os.getcwd(), 'cache')
        
        self.base_cache_dir = Path(base_cache_dir)
        self.current_server = None
        self.current_server_port = None
        
        # Create base directories
        self._ensure_directories()
        
        logger.info(f"Cache manager initialized with base directory: {self.base_cache_dir}")
    
    def _ensure_directories(self):
        """Ensure cache directories exist"""
        # Create base cache directory
        self.base_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        self.levels_dir = self.base_cache_dir / 'levels'
        self.assets_dir = self.base_cache_dir / 'assets'
        self.assets_dir.mkdir(exist_ok=True)
        
        # Asset subdirectories
        (self.assets_dir / 'images').mkdir(exist_ok=True)
        (self.assets_dir / 'sounds').mkdir(exist_ok=True)
        (self.assets_dir / 'animations').mkdir(exist_ok=True)
        (self.assets_dir / 'misc').mkdir(exist_ok=True)
    
    def set_server(self, server: str, port: int):
        """Set the current server for level organization
        
        Args:
            server: Server hostname/IP
            port: Server port
        """
        self.current_server = server
        self.current_server_port = port
        
        # Create server-specific level directory
        server_dir = self._get_server_dir()
        server_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Set server to {server}:{port}, level cache: {server_dir}")
    
    def _get_server_dir(self) -> Path:
        """Get the server-specific directory for levels"""
        if not self.current_server:
            raise ValueError("No server set - call set_server() first")
        
        # Create a safe directory name from server:port
        server_name = f"{self.current_server}_{self.current_server_port}"
        # Replace problematic characters
        server_name = server_name.replace(':', '_').replace('.', '_')
        
        return self.levels_dir / server_name
    
    def get_cache_path(self, filename: str, file_data: Optional[bytes] = None) -> Path:
        """Get the appropriate cache path for a file
        
        Args:
            filename: Name of the file
            file_data: Optional file data to determine type
            
        Returns:
            Path where the file should be cached
        """
        filename_lower = filename.lower()
        
        # Level files (.nw, .reborn, .zelda) go to server-specific directory
        if any(filename_lower.endswith(ext) for ext in ['.nw', '.reborn', '.zelda']):
            if not self.current_server:
                logger.warning(f"No server set for level file {filename}, using default")
                return self.levels_dir / 'default' / filename
            return self._get_server_dir() / filename
        
        # GMAP files also go to server directory
        if filename_lower.endswith('.gmap'):
            if not self.current_server:
                return self.levels_dir / 'default' / filename
            return self._get_server_dir() / filename
        
        # Asset files go to shared assets directory
        if any(filename_lower.endswith(ext) for ext in ['.png', '.gif', '.jpg', '.jpeg', '.bmp']):
            return self.assets_dir / 'images' / filename
        
        if any(filename_lower.endswith(ext) for ext in ['.wav', '.mp3', '.ogg', '.mid', '.midi']):
            return self.assets_dir / 'sounds' / filename
        
        if filename_lower.endswith('.gani'):
            return self.assets_dir / 'animations' / filename
        
        # Everything else goes to misc
        return self.assets_dir / 'misc' / filename
    
    def save_file(self, filename: str, file_data: bytes) -> Path:
        """Save a file to the appropriate cache location
        
        Args:
            filename: Name of the file
            file_data: File data to save
            
        Returns:
            Path where the file was saved
        """
        cache_path = self.get_cache_path(filename, file_data)
        
        # Ensure parent directory exists
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save the file (always save, even if cache reads are disabled)
        with open(cache_path, 'wb') as f:
            f.write(file_data)
        
        if self.disabled:
            logger.debug(f"Saved file (cache reads disabled, but still saving): {cache_path}")
        else:
            logger.debug(f"Saved file to cache: {cache_path}")
            
        return cache_path
    
    def get_file(self, filename: str) -> Optional[bytes]:
        """Get a file from cache if it exists
        
        Returns None if cache is disabled (forcing fresh download)
        
        Args:
            filename: Name of the file
            
        Returns:
            File data if found and cache enabled, None otherwise
        """
        if self.disabled:
            # Cache reads disabled - always return None to force download
            logger.debug(f"Cache reads disabled - forcing download of {filename}")
            return None
            
        cache_path = self.get_cache_path(filename)
        
        if cache_path.exists():
            with open(cache_path, 'rb') as f:
                logger.debug(f"Found {filename} in cache")
                return f.read()
        
        return None
    
    def file_exists(self, filename: str) -> bool:
        """Check if a file exists in cache
        
        Args:
            filename: Name of the file
            
        Returns:
            True if file exists in cache AND cache reads are enabled
        """
        if self.disabled:
            # Always return False to force re-download
            return False
            
        cache_path = self.get_cache_path(filename)
        return cache_path.exists()
    
    def get_asset_paths(self) -> Dict[str, Path]:
        """Get all asset directory paths for game loading
        
        Returns:
            Dictionary of asset type to path
        """
        # Always return paths, even if cache reads are disabled
        # (we still save files, just don't read from cache)
        return {
            'images': self.assets_dir / 'images',
            'sounds': self.assets_dir / 'sounds',
            'animations': self.assets_dir / 'animations',
            'misc': self.assets_dir / 'misc',
            'base': self.assets_dir
        }
    
    def clear_cache(self, levels_only: bool = False):
        """Clear cache files
        
        Args:
            levels_only: If True, only clear level files
        """
        # Always allow clearing cache, even if reads are disabled
            
        if levels_only and self.current_server:
            server_dir = self._get_server_dir()
            if server_dir.exists():
                import shutil
                shutil.rmtree(server_dir)
                server_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Cleared level cache for {self.current_server}:{self.current_server_port}")
        else:
            # Clear everything
            import shutil
            if self.base_cache_dir.exists():
                shutil.rmtree(self.base_cache_dir)
                self._ensure_directories()
                logger.info("Cleared entire cache")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about cache usage
        
        Returns:
            Dictionary with cache statistics
        """
        def get_dir_size(path: Path) -> int:
            """Get total size of directory"""
            total = 0
            if path.exists():
                for p in path.rglob('*'):
                    if p.is_file():
                        total += p.stat().st_size
            return total
        
        def count_files(path: Path) -> int:
            """Count files in directory"""
            if path.exists():
                return sum(1 for p in path.rglob('*') if p.is_file())
            return 0
        
        info = {
            'base_dir': str(self.base_cache_dir),
            'current_server': f"{self.current_server}:{self.current_server_port}" if self.current_server else None,
            'total_size': get_dir_size(self.base_cache_dir),
            'level_count': count_files(self.levels_dir),
            'asset_count': count_files(self.assets_dir),
            'assets': {
                'images': count_files(self.assets_dir / 'images'),
                'sounds': count_files(self.assets_dir / 'sounds'),
                'animations': count_files(self.assets_dir / 'animations'),
                'misc': count_files(self.assets_dir / 'misc')
            }
        }
        
        return info
    
    def get_cached_level_files(self) -> List[str]:
        """Get list of all cached level files for current server
        
        Returns:
            List of level file names (without .nw extension)
        """
        if not self.current_server:
            logger.warning("No server set - cannot get cached level files")
            return []
        
        try:
            server_dir = self._get_server_dir()
            if not server_dir.exists():
                return []
            
            level_files = []
            for file_path in server_dir.glob('*.nw'):
                # Remove .nw extension to get level name
                level_name = file_path.stem
                level_files.append(level_name)
            
            return sorted(level_files)
            
        except Exception as e:
            logger.error(f"Error getting cached level files: {e}")
            return []
    
    def get_cached_gmap_files(self) -> List[str]:
        """Get list of all cached GMAP files for current server
        
        Returns:
            List of GMAP file names
        """
        if not self.current_server:
            logger.warning("No server set - cannot get cached GMAP files")
            return []
        
        try:
            server_dir = self._get_server_dir()
            if not server_dir.exists():
                return []
            
            gmap_files = []
            for file_path in server_dir.glob('*.gmap'):
                gmap_files.append(file_path.name)
            
            return sorted(gmap_files)
            
        except Exception as e:
            logger.error(f"Error getting cached GMAP files: {e}")
            return []
    
    def is_level_cached(self, level_name: str) -> bool:
        """Check if a specific level is cached
        
        Args:
            level_name: Name of level to check (with or without .nw extension)
            
        Returns:
            True if level is cached
        """
        if not self.current_server:
            return False
        
        try:
            # Ensure .nw extension
            if not level_name.endswith('.nw'):
                level_name += '.nw'
            
            cache_path = self.get_cache_path(level_name)
            return cache_path.exists()
            
        except Exception as e:
            logger.debug(f"Error checking if level is cached: {e}")
            return False
    
    def get_cache_coverage_for_gmap(self, gmap_levels: List[str]) -> Dict[str, Any]:
        """Get cache coverage statistics for a GMAP's levels
        
        Args:
            gmap_levels: List of level names in the GMAP
            
        Returns:
            Dictionary with coverage statistics
        """
        if not gmap_levels:
            return {'cached_count': 0, 'total_count': 0, 'coverage_percentage': 0, 'missing_levels': []}
        
        cached_count = 0
        missing_levels = []
        
        for level_name in gmap_levels:
            if self.is_level_cached(level_name):
                cached_count += 1
            else:
                missing_levels.append(level_name)
        
        total_count = len(gmap_levels)
        coverage_percentage = (cached_count / total_count * 100) if total_count > 0 else 0
        
        return {
            'cached_count': cached_count,
            'total_count': total_count,
            'coverage_percentage': coverage_percentage,
            'missing_levels': missing_levels,
            'cached_levels': [level for level in gmap_levels if level not in missing_levels]
        }