[![Gitter](https://badges.gitter.im/Manga-Tagger/community.svg)](https://gitter.im/Manga-Tagger/community?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge)
![GitHub all releases](https://img.shields.io/github/downloads/Inpacchi/Manga-Tagger/total)
![GitHub issues](https://img.shields.io/github/issues/Inpacchi/Manga-Tagger)

![Manga Tagger Logo](images/manga_tagger_logo_cropped.png)

A tool to rename and write metadata to digital manga chapters

## Background and Inspiration
Where do I even start...well, I **really** enjoy Japanese culture, specifically anime and manga. While there is a lot of support for American comics in a digital format, the same cannot be said about manga. One day, I stumbled across Free Manga Downloader, which allowed me to start my digital manga library. However, the one pitfall of the application is the lack of capability for grabbing metadata.

Being an American comic fan, I regularly use ComicRack and [Comic Tagger](https://github.com/comictagger/comictagger). While Comic Tagger works with manga, it wasn't **made** for manga and so it's implementation in that regard is lackluster. And thus, this project was born...

## Features
* Direct integration with [Free Manga Downloader 2](https://github.com/dazedcat19/FMD2)
* Scrapes metadata from [Anilist](https://anilist.co/) and [MyAnimeList](https://myanimelist.net/) (using [Jikan](https://jikan.moe/))
* Fully automated batch processing
* Extremely easy integration with [DataDog](https://www.datadoghq.com/) for log monitoring
* Multithreaded for handling multiple files at a time
* Writes metadata in the ComicRack format (using comicinfo.xml)
* Full support for strictly **CBZ** files

## Prerequisites

* Windows OS
* [Free Manga Downloader 2](https://github.com/dazedcat19/FMD2)
* [Python 3.7](https://www.python.org/)
* [MongoDB](https://www.mongodb.com/)

## Installation

Download the latest release.

Extract the folder to your desired location (preferably the same parent directory as Free Manga Downloader.)

Once extracted, you can either install Manga Tagger as a service using [NSSM](https://nssm.cc/) and the included `install.bat` **(recommended)** or run it on-demand using `run.bat`.

### Database Configuration
In MongoDB, you don't need to explicitly define a database before assigning a user read/write permissions to it. Therefore, all you need to do in MongoDB is run the following command in the mongo shell with the authentication database you prefer:
```
db.createUser({
  user:"<APPLICATION_USER>",
  pwd:"<PASSWORD>",
  roles:[
    { role: "readWrite", db: "manga_tagger" }
  ]
})
```

## Settings

* application
  * timezone - Select a timezone from https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
    * default: "America/New_York"
  * library
    * dir (Directory) - Define a location for your manga library (Manga Tagger will create it if the directory does not exist.)
	  * default: "C:\Library"
	* is_network_path - Set to true if your manga library directory is on a network share; false if not
	  * default: false
  * dry_run (DEVELOPMENT SETTING ONLY)
    * enabled - Set to true to prevent Manga Tagger from certain processing
	  * default: false
	* rename_file - Disable Manga Tagger from renaming files while set to false
	  * default: false
	* database_insert - Disable Manga Tagger from inserting records into the database while set to false
	  * default: false
	* write_comicinfo - Disable Manga Tagger from writing the comicinfo.xml to files while set to false
	  * default: false
  * multithreading
    * threads - Define an amount of worker threads for Manga Tagger to spawn
	  * default: 8
	* max_queue_size - Define the maximum size the file queue should be for worker threads
	  * default: 0
* database (Only MongoDB is supported at this time)
  * database_name - Define the name of your database
	  * default: "manga_tagger" **(recommended)**
  * host_address - Define the hostname/IP address of your database
	  * default: "localhost"
  * port - Define the port of your database
	  * default: 27017
  * username - Define the username used to connect to your database
	  * default: "manga_tagger"
  * password - Define the password used to connect to your database
	  * default: "Manga4LYFE"
  * auth_source - Define the authentication table used for your defined username
	  * default: "admin"
  * server_selection_timeout_ms - Define the server selection timeout (in milliseconds) which depends on your network connection and server configuration
	  * default: 1
* logger
  * logging_level - Can be set to "info" or "debug"
    	* default: "info"
  * log_dir - Set the default location of the logs folder
    	* default: "logs" **(recommended)**
  * max_size - Set the maximum size of a log file (in bytes)
    	* default: 10485760
  * backup_count - Set the amount of log files to keep
    	* default: 5
  * console
    * enabled - Set to true to enable console logging
      * default: false
      * log_format - Set the format of the logs
      * default: "%(asctime)s | %(threadName)s %(thread)d | %(name)s | %(levelname)s - %(message)s"
  * file
    * enabled - Set to true to enable file-based logging
      * default: true
    * log_format - Set the format of the logs
      * default: "%(asctime)s | %(threadName)s %(thread)d | %(name)s | %(levelname)s - %(message)s"
  * json
    * enabled - Set to true to enable JSON logging to file (used for DataDog integration)
      * default: false
    * log_format - Set the format of the logs
      * default: "%(asctime)s %(threadName)s %(thread)d %(name)s %(levelname)s %(message)s"
  * tcp
    * enabled - Set to true to enable TCP logging
      * default: false
    * host - Define the hostname (typically localhost) of where to host the TCP logs
      * default: "localhost"
    * port - Set to true to enable console logging
      * default: 1798
    * log_format - Set the format of the logs
      * default: "%(asctime)s | %(threadName)s %(thread)d | %(name)s | %(levelname)s - %(message)s"
  * json_tcp
    * enabled - Set to true to enable JSON TCP logging
      * default: false
    * host - Define the hostname (typically localhost) of where to host the JSON TCP logs
      * default: "localhost"
    * port - Set to true to enable console logging
      * default: 1798
    * log_format - Set the format of the logs
      * default: "%(asctime)s %(threadName)s %(thread)d %(name)s %(levelname)s %(message)s"
* fmd (Free Manga Downloader integration settings)
  * fmd_dir (FMD Directory) - Set the home location of Free Manga Downloader
    	* default: C:\Free Manga Downloader
  * download_dir (Download Directory) - (DEVELOPMENT SETTING ONLY) If set, override the FMD download directory
  	* default: null

## Planned Development

#### Features
* Unit testing

#### Optimizations
* MongoDB Table Links (look at serializations and staff)
* Check staff roles for multiple staff under a single role
* Check serializations for multiple publishers

## Support

Log issues via [GitHub](https://github.com/ivtechboyinpa/Manga-Tagger/issues)

## Contributing
Pull requests are always welcome. For major changes, please open an issue first to discuss what you would like to change.

If you have any questions, please feel free to reach out on Gitter.

## License
[MIT](https://choosealicense.com/licenses/mit/)
