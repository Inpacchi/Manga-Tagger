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

## [Installation & Configuration](https://github.com/Inpacchi/Manga-Tagger/wiki/Installation-&-Configuration)

## [Settings](https://github.com/Inpacchi/Manga-Tagger/wiki/Setting-Configuration)

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

If you have any questions, please feel free to reach out on our [GitHub Discussions](https://github.com/Inpacchi/Manga-Tagger/discussions).

## License
[MIT](https://choosealicense.com/licenses/mit/)
