# Pico Environment Archive Backup

There is a backup repository for PICO theme list from `https://picoenvironmentarchive.gt.tc/`.

All data collected from original site, I am not responsible for security.

The script will write files below:

```text
data/
  themes.original.json
  themes.json
  environments/
    {id}.html
  themes/
    {id}.json
  images/
    {id}.webp
```

- `data/themes.original.json` is the original theme list.
- `data/themes.json` is merged by all `data/themes/{id}.json` files.
- `data/themes/{id}.json` contains original data, and added download url parsed from original html.
- `data/images/{id}.webp` are not original picture, they have all been compressed to webp.
