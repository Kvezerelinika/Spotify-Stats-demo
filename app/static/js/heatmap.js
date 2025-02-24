// Assuming "daily_listening_time" is passed as JSON from the backend
const dailyListeningData = JSON.parse(document.getElementById('listening-data').textContent);

// Convert data into a format suitable for D3.js
const heatmapData = dailyListeningData.map(entry => ({
    date: new Date(entry.play_date),
    hours: entry.daily_hours || 0, // Ensure it has a default value
    songs: entry.daily_songs || 0
}));

// Set up D3.js SVG container
const width = 800, height = 150, cellSize = 15;
const svg = d3.select("#heatmap").append("svg")
    .attr("width", width)
    .attr("height", height);

// Define a color scale based on hours listened
const colorScale = d3.scaleSequential(d3.interpolateBlues)
    .domain([0, d3.max(heatmapData, d => d.hours)]);

// Generate the heatmap
svg.selectAll("rect")
    .data(heatmapData)
    .enter().append("rect")
    .attr("x", (d, i) => (i % 52) * cellSize)  // 52 weeks grid
    .attr("y", (d, i) => Math.floor(i / 52) * cellSize)
    .attr("width", cellSize - 2)
    .attr("height", cellSize - 2)
    .attr("fill", d => colorScale(d.hours))
    .on("mouseover", function (event, d) {
        d3.select("#tooltip")
          .style("left", (event.pageX + 10) + "px")
          .style("top", (event.pageY - 20) + "px")
          .style("display", "block")
          .html(`Date: ${d.date.toDateString()}<br>Hours: ${d.hours.toFixed(1)}h<br>Songs: ${d.songs}`);
    })
    .on("mouseout", () => d3.select("#tooltip").style("display", "none"));