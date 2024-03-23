# yaptide backend

## Getting the code

Clone the repository including submodules:

```shell
git clone --recurse-submodules https://github.com/yaptide/yaptide.git
```

In case you have used regular `git clone` command, without `--recurse-submodules` option, you can still download the submodules by running:

```shell
git submodule update --init --recursive
```

## Building and running the app

There are two main ways of build and run the app
- For developers, which is setting up all components manually. It is faster then Docker.
    - [For Linux developers](./docs/for_linux_developers.md)
    - [For Windows developers](./docs/for_windows_developers.md)
- [Using Docker](./docs/using_docker.md). Used for the deployment, takes more time.


## Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
