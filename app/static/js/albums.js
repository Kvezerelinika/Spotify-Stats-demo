function filterAlbums() {
    const search = document.getElementById("search").value;
    const sort = document.getElementById("sort").value;

    fetch(`/albums/filter?search=${search}&sort=${sort}`)
        .then(res => res.json())
        .then(data => {
            document.getElementById("album-list").innerHTML = data.html;
        });
}

function openAlbumModal(albumId) {
    fetch(`/albums/details/${albumId}`)
        .then(res => res.text())
        .then(html => {
            document.getElementById("albumModalContent").innerHTML = html;
            document.getElementById("albumModal").style.display = "block";
        });
}
