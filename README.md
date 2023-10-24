![GitHub tag (latest by date)](https://img.shields.io/github/v/tag/SanchoBlaze/Manga-Tagger?label=latest)  ![GitHub issues](https://img.shields.io/github/issues/sanchoblaze/Manga-Tagger) 
![Docker Cloud Build Status](https://img.shields.io/docker/cloud/build/sanchoblaze/manga-tagger)
 ![Docker Pulls](https://img.shields.io/docker/pulls/sanchoblaze/manga-tagger) ![GitHub all releases](https://img.shields.io/github/downloads/SanchoBlaze/Manga-Tagger/total)

![Manga Tagger Logo](https://raw.githubusercontent.com/SanchoBlaze/Manga-Tagger/main/images/manga_tagger_logo_cropped.png)

A tool to rename and write metadata to digital manga chapters, forked from [Inpacchi/Manga-Tagger](https://github.com/Inpacchi/Manga-Tagger). 

## Features
* Converted to Docker to so it can be run anywhere.
* Switched to SQLite instead of MongoDB to increase portability.
* Point the container at your download and library folder and let it take care of the rest.
* Scrapes metadata from [Anilist](https://anilist.co/) and [MyAnimeList](https://myanimelist.net/) (using [Jikan](https://jikan.moe/)).
* Fully automated batch processing.
* Multithreaded for handling multiple files at a time
* Writes metadata in the ComicRack format (using comicinfo.xml)
* Full support for strictly **CBZ** files

## Installation
**docker-compose:**

    services:  
      manga-tagger:  
        image: sanchoblaze/manga-tagger  
        container_name: manga-tagger  
        volumes:  
          - /path/to/library:/library  
          - /path/to/downloads:/downloads  
          - /path/to/config:/config

**docker cli:**

    docker run -d \
      --name=manga-tagger \
      -v /path/to/library:/library \
      -v /path/to/downloads:/downloads \
      -v /path/to/config:/config \
      --restart unless-stopped \
      sanchoblaze/manga-tagger:latest

## File Naming

Files to be processed, should be named in the format:

> MANGA -.- CHAPTER

For example:
> Akira -.- Chapter 001.cbz

This will be renamed to
> Akira 001.cbz


## Support

Log issues via [GitHub](https://github.com/sanchoblaze/Manga-Tagger/issues)

## Contributing
Pull requests are always welcome. For major changes, please open an issue first to discuss what you would like to change.

If you have any questions, please feel free to reach out on our [GitHub Discussions](https://github.com/sanchoblaze/Manga-Tagger/discussions).

## License
[MIT](https://choosealicense.com/licenses/mit/)
