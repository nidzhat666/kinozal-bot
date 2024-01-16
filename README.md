Kinozal Movie Finder Bot for Telegram and qBittorrent
=============================================

Introduction
------------

The Movie Finder Bot is a Telegram bot designed to facilitate easy searching and downloading of movies via the Kinozal cinema database and qBittorrent. It integrates with Telegram to provide a seamless experience from search to download.

Features
--------

*   **Search**: Users can search Kinozal's extensive movie database directly from Telegram using the `/search` command.
*   **Interactive Results**: Search results are returned as inline buttons in Telegram for easy selection.
*   **Torrent Details**: Detailed information about each movie is provided, including ratings and descriptions.
*   **Adaptive Download Categories**: Movies can be downloaded into specific categories within qBittorrent, automatically pulled from Kinozal.
*   **Kinozal Direct Access**: The bot provides a button to open the selected movie on Kinozal's website.
*   **Status Updates**: The `/status` command allows users to check the progress of downloads in qBittorrent.

Setup
-----

### Prerequisites

*   Docker and Docker Compose
*   qBittorrent with Web UI enabled
*   A Telegram bot token

### Environment Setup

Create a `.env` file with the following contents:

    # Telegram Bot Info
    TELEGRAM_BOT_TOKEN=<Your_Telegram_Bot_Token>
    
    # Kinozal Credentials
    KINOZAL_USERNAME=<Your_Kinozal_Username>
    KINOZAL_PASSWORD=<Your_Kinozal_Password>
    
    # Docker Configuration
    LOCAL_BUILD=1
    
    # qBittorrent Configuration
    QBT_HOST=http://localhost
    QBT_USERNAME=admin
    QBT_PASSWORD=<Your_qBittorrent_Password>
    QBT_PORT=8080
    
    # Redis Configuration
    REDIS_HOST=localhost
    REDIS_PORT=6379
    REDIS_DB=0
    

### Running the Bot

To start the bot, navigate to the directory containing your `docker-compose.yml` and `.env` files and run:

    docker-compose up -d

Usage
-----

With the bot up and running, simply send the `/search` command followed by your query to start searching for movies. Follow the interactive prompts to select a movie and manage your downloads.

Contributing
------------

Feel free to fork the repository, make improvements, and submit pull requests. We appreciate your contributions to make the Movie Finder Bot even better!


Support
-------

If you encounter any issues or have any questions, please file an issue on the repository's issue tracker.
