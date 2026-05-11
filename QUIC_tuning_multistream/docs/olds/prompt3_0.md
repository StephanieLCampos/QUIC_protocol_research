
We have two steps:
1. Create a requirements_v3.md based on the contents of requirements_v2.md and adding sections for code organization under the 
@code/ directory. The organization should support locations for the main code, aioquic library source code, simulation code.

We have two steps:
1. Create a requirements_v3.md based on the contents of requirements_v2.md and adding sections for code organization under the 
@code/ directory. The organization should support locations for the main code, aioquic library source code, simulation code.

the simulation code should consist of 3 different simulations types. All simulations recieve the values of the 3 parameters, execute the QUIC connection with 3 streams open, but only one is sending data and each simulation type will synthesize data correlating for each application type (video streaming, conference call, file transfer). 

The grid search code should run all the different combinations of parameter values based off their ranges, for each simulation type.
 While these simulations are happening, everything should be saved and when everything is done, the results should be shown in results.md
The results should consist of the parameter values used, the data type selected, and the results of the metrics. This should be shown for every data type and organized by that manner. 
For the results of each data type, there should be a "best values" column that displays the best parameters values for that certain data type.
What is considered the best for each data type is parameters that give:
- Video Streaming: the lowest latency
- File Transfer: the highest throughput
- Conference Calls: the lowest jitter 

the data-synthesizing code
the simulation code: open a connect with 3 streams and send the snythesisxed data
the metric measurement code:
the grid search code: superzie the synthesize, the transport and capture the metrics
the results code: collect all the grid search data, execute





## NOTE:
- We will have three different application types:
    - File Transfer
    - Video Conference
    - Video Streaming
- Each one of these will have its own type of synthesized data.

## Data-synthesizing code
- Will generate 3 different types of synthesized data for each of the following applications: 
    - video streaming
    - conference call
    - file transfer

## Simulation code
- receives the parameters and application type to be used
- set the parameters to the selected values
- get the data synthesizer for the application type 
- a simulation feeds the sysnthetized data into the aioquic library configured opening a QUIC connection with 3 streams, and sending the synthtized data through only one of the streams.
- During the execution the Metric Measurement Code will collect the metric values and save them in a csv file.

## Metric Measurement code
- There are 5 performance metrics: 
    - Throughput
    - Round-Trip Time (RTT)
    - Jitter
    - Packet Loss Rate
    -Connection Establishment Time
- This compomemt captures the values for the 5 metrics for the QUIC connection
- Measuremetics will be saved in an csv file named using the following template:
    - file name: <application_type>_<Initial_Congestion_Window>_<Max_ACK_Delay>_<Loss_Reduction_Factor>.csv
- Measurement files are CSV files containing values for the following fields:
        - Initial Congestion Window (parameter 1)
        - Max ACK Delay (Parameter 2)
        - Loss Reduction Factor (Parameter 3)
        - Throughput
        - Round-Trip Time (RTT)
        - Jitter
        - Packet Loss Rate
        -Connection Establishment Time

## Grid Search code
- Supervises all of the synthesizing and transportation of data.
- for each application type perform a grid search over the following parameters (variables): 
    - Initial Congestion Window
    - Max ACK Delay
    - Loss Reduction Factor

- Each parameter will have 4 possible values. Please select the 4 values of each parameter accordingly, based on the range of each parameter. 
- For each grid iteration, run a simulation for the application type and a combination of parameter values.


## Results code
- Once Grid Search code execution is done, files for all combinations are available and we will use these files to produce a final research report presenting insights consisting of:
    -The measured metrics and best set of parameters that give:
        - Video Streaming: the lowest latency
        - File Transfer: the highest throughput
        - Conference Calls: the lowest jitter 
    - Any trends you notice from the data





